#include <SPI.h>
#include <mcp2515.h>
#include <PID_v1_bc.h>

// ===================== 硬件引脚 =====================
#define MCP2515_CS_PIN  10
// Mega2560硬件SPI：D50=MISO, D51=MOSI, D52=SCK

// ===================== CAN协议参数（严格匹配官方） =====================
#define CAN_BAUD_RATE   CAN_1000KBPS   // 官方波特率：1Mbps
#define MOTOR_ID        2              // 电机ID，对应拨码001
#define SPEED_CMD_ID    0x202          // 速度控制标准帧ID
#define ACTIVATE_CMD_ID 0x300          // 配置/激活指令帧ID
#define SPEED_FEEDBACK_ID 0x208        // 1号电机状态反馈帧ID

// ===================== PID控制参数 =====================
double targetRPM = 300;   // 初始目标转速，范围-2048~2047
double actualRPM = 0;
double pidOutput = 0;
double Kp = 1.0;
double Ki = 0.05;
double Kd = 0.02;

PID myPID(&actualRPM, &pidOutput, &targetRPM, Kp, Ki, Kd, DIRECT);

// ===================== 控制标志 =====================
bool motorEnable = false;

// ===================== 上位机失联保护 =====================
// Python闭环运行时每50ms发送一次合法T指令；超过500ms未收到S/T则独立停机。
const unsigned long CONTROL_TIMEOUT_MS = 500;
unsigned long lastControlCommandTime = 0;

// ===================== CAN对象 =====================
MCP2515 mcp2515(MCP2515_CS_PIN);
struct can_frame rxFrame;
struct can_frame txFrame;
unsigned long lastSendTime = 0;
const long sendInterval = 10;

// ===================== 串口缓存 =====================
String inputString = "";

void setup() {
  Serial.begin(115200);
  inputString.reserve(200);

  Serial.println("===== 施罗德电机PID控制系统启动 =====");
  Serial.println("指令：S启动 / P停止 / T+转速 / Kp=数值 / Ki=数值 / Kd=数值");

  // 初始化CAN（标准帧、1Mbps）
  SPI.begin();
  mcp2515.reset();
  mcp2515.setBitrate(CAN_BAUD_RATE, MCP_16MHZ);
  mcp2515.setNormalMode();
  Serial.println("CAN总线初始化完成（1Mbps 标准帧）");

  // 发送驱动激活指令（必须步骤）
  activateMotor(MOTOR_ID);
  Serial.println("已发送电机激活指令");

  // 初始化PID
  myPID.SetMode(AUTOMATIC);
  myPID.SetSampleTime(10);
  myPID.SetOutputLimits(-2047, 2047);  // 匹配协议速度范围
  lastControlCommandTime = millis();
  Serial.println("PID初始化完成，电机默认关闭");
  Serial.println("====================================");
}

void loop() {
  unsigned long now = millis();

  // ---------- 0. 上位机控制命令超时保护 ----------
  // unsigned long减法可正确处理millis()回绕。
  if (motorEnable && (unsigned long)(now - lastControlCommandTime) > CONTROL_TIMEOUT_MS) {
    safeStopMotor();
    Serial.println("[故障] WATCHDOG_TIMEOUT: 上位机控制命令超时，电机已停止");
  }

  // ---------- 1. 读取电机转速反馈 ----------
  if (mcp2515.readMessage(&rxFrame) == MCP2515::ERROR_OK) {
    if (rxFrame.can_id == SPEED_FEEDBACK_ID && rxFrame.can_dlc >= 6) {
      // 转速在DATA4(高8位)、DATA5(低8位)，16位有符号大端序
      actualRPM = (int16_t)(
        ((uint16_t)rxFrame.data[4] << 8) |
        (uint16_t)rxFrame.data[5]
      );
    }
  }

  // ---------- 2. 周期执行PID与速度指令 ----------
  if (now - lastSendTime >= sendInterval) {
    lastSendTime = now;

    if (motorEnable) {
      myPID.Compute();
      sendSpeedCommand(MOTOR_ID, (int16_t)pidOutput);
    } else {
      sendSpeedCommand(MOTOR_ID, 0);
    }

    // 每100ms打印一次数据
    static unsigned long lastPrint = 0;
    if (now - lastPrint >= 100) {
      lastPrint = now;
      Serial.print("目标:");
      Serial.print(targetRPM);
      Serial.print(",实际:");
      Serial.print(actualRPM);
      Serial.print(",输出:");
      Serial.println(pidOutput);
    }
  }

  // ---------- 3. 处理串口指令 ----------
  serialEvent();
}

/**
 * @brief 激活指定ID的电机驱动
 */
void activateMotor(uint8_t id) {
  txFrame.can_id = ACTIVATE_CMD_ID;
  txFrame.can_dlc = 8;
  // 所有通道默认填0xFF（无效）
  for (int i=0; i<8; i++) txFrame.data[i] = 0xFF;
  // 对应电机通道填激活命令字0x00
  txFrame.data[id - 1] = 0x00;
  mcp2515.sendMessage(&txFrame);
}

/**
 * @brief 发送速度闭环指令（标准帧0x202）
 */
void sendSpeedCommand(uint8_t id, int16_t speed) {
  txFrame.can_id = SPEED_CMD_ID;
  txFrame.can_dlc = 8;
  // 所有通道默认填0xFF（无效）
  for (int i=0; i<8; i++) txFrame.data[i] = 0xFF;

  // 计算对应电机的字节偏移（每个电机占2字节，高8位在前）
  uint8_t offset = (id - 1) * 2;
  txFrame.data[offset]     = (speed >> 8) & 0xFF;  // 高8位
  txFrame.data[offset + 1] = speed & 0xFF;         // 低8位

  mcp2515.sendMessage(&txFrame);
}

/**
 * @brief 立即进入安全停止状态，并清除PID内部累积状态
 */
void safeStopMotor() {
  motorEnable = false;
  targetRPM = 0;
  myPID.SetMode(MANUAL);
  pidOutput = 0;
  myPID.SetMode(AUTOMATIC);
  sendSpeedCommand(MOTOR_ID, 0);
}

/**
 * @brief 串口指令解析
 */
void serialEvent() {
  while (Serial.available()) {
    char inChar = (char)Serial.read();
    if (inChar == '\n') {
      inputString.trim();
      inputString.toUpperCase();
      parseCommand(inputString);
      inputString = "";
    } else {
      inputString += inChar;
    }
  }
}

void parseCommand(String cmd) {
  if (cmd == "S" || cmd == "START") {
    motorEnable = true;
    lastControlCommandTime = millis();
    Serial.println("[指令] 电机已启动");
  }
  else if (cmd == "P" || cmd == "STOP") {
    safeStopMotor();
    Serial.println("[指令] 电机已停止");
  }
  else if (cmd.startsWith("T")) {
    String speedText = cmd.substring(1);
    bool validNumber = speedText.length() > 0;
    unsigned int firstDigit = 0;
    if (validNumber && (speedText.charAt(0) == '+' || speedText.charAt(0) == '-')) {
      firstDigit = 1;
    }
    if (firstDigit >= speedText.length()) {
      validNumber = false;
    }
    for (unsigned int i = firstDigit; validNumber && i < speedText.length(); i++) {
      if (!isDigit(speedText.charAt(i))) {
        validNumber = false;
      }
    }
    if (!validNumber) {
      Serial.println("[错误] 目标转速必须是整数");
      return;
    }

    long speed = speedText.toInt();
    if (speed >= -2047 && speed <= 2047) {
      targetRPM = speed;
      lastControlCommandTime = millis();
      Serial.print("[指令] 目标转速设为：");
      Serial.println(targetRPM);
    } else {
      Serial.println("[错误] 转速范围 -2047 ~ 2047 rpm");
    }
  }
  else if (cmd.startsWith("KP=")) {
    Kp = cmd.substring(3).toDouble();
    myPID.SetTunings(Kp, Ki, Kd);
    Serial.print("[指令] Kp设为：");
    Serial.println(Kp);
  }
  else if (cmd.startsWith("KI=")) {
    Ki = cmd.substring(3).toDouble();
    myPID.SetTunings(Kp, Ki, Kd);
    Serial.print("[指令] Ki设为：");
    Serial.println(Ki);
  }
  else if (cmd.startsWith("KD=")) {
    Kd = cmd.substring(3).toDouble();
    myPID.SetTunings(Kp, Ki, Kd);
    Serial.print("[指令] Kd设为：");
    Serial.println(Kd);
  }
  else {
    Serial.println("[错误] 未知指令");
  }
}

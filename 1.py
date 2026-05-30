import cv2
import numpy as np
image_path=r'D:\OIP.webp'
image=cv2.imread(image_path)
gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
v = np.median(gray)
TL = 0.66 * v
TH = 1.33 * v
image=cv2.Canny(image,TL,TH,3,L2gradient=True)
contours,hau=cv2.findContours(image,cv2.RETR_TREE,cv2.CHAIN_APPROX_SIMPLE)


if image is None:
    print("图片读取失败")
cv2.imshow("图片展示",image)
key=cv2.waitKey(0)
if key==ord('s'):
    output_path=r"D:\pythonsrc\save\saved_image.jpg"
    cv2.imwrite(output_path,image)
else:
    print('图像未保存')
cv2.destroyAllWindows()
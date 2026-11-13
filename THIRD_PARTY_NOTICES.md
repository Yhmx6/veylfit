# 第三方组件与素材

本仓库仅包含通用模型与无真人身份的示意图，不分发用户档案、真人照片或生成的人物基准。

- MakeHuman 标准男女人体网格及骨架：由标准模板导出，CC0；原文见 `src/veylfit/templates/MakeHuman-LICENSE.ASSETS.md`。[官方许可说明](https://www.makehumancommunity.org/about/license.html)。没有打包 MakeHuman 程序本身。
- MediaPipe BlazePose GHUM / Pose Landmarker：本地关节点与分割；Apache-2.0。[官方模型卡](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20BlazePose%20GHUM%203D.pdf)。图像深度不是厘米级真实深度。
- MediaPipe BlazeFace Short Range：本地面部定位；Apache-2.0。[官方模型卡](https://storage.googleapis.com/mediapipe-assets/MediaPipe%20BlazeFace%20Model%20Card%20%28Short%20Range%29.pdf)。不执行身份识别。
- 三张体型手绘选项图：本项目生成的通用示意图，不是照片或医学测量图。
- Python、Tcl/Tk、NumPy、Pillow、MediaPipe、OpenCV、Matplotlib及传递依赖：随安装包附带原始许可；构建版本见 `requirements-lock.txt`，许可文本见 `licenses/`。
- PyInstaller：GPL with bootloader exception，打包程序可独立许可；[官方说明](https://www.pyinstaller.org/en/stable/license.html)。
- 安装程序由 Inno Setup 制作，保留其内置版权与许可。[Inno Setup License](https://jrsoftware.org/files/is/license.txt)。

模型资产校验值见 `packaging/assets-manifest.json`。应用默认不自动上传图片，也不在客户端嵌入共享生图服务密钥。

本项目自v0.2.1起，对有权许可的原创代码、构建脚本、测试和文档采用[PolyForm Noncommercial 1.0.0](LICENSE)，详见[适用范围](LICENSE-SCOPE.md)。该选择不改变上列第三方组件及资产的原有许可，不把CC0或Apache-2.0资源限制为非商业使用。

安装目录根部包含项目许可和本说明；原始第三方许可在licenses目录。通用模型及素材在_internal/templates、_internal/face_assets、_internal/pose_assets、_internal/shape_assets，对应本仓库src/veylfit下同名目录。

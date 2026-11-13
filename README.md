# 映衣间 · Veylfit

先看见穿在自己身上的样子，再决定怎么穿。

Windows桌面试衣测试版 **0.2.0**：人物建档与试衣搭配两个模块。生图采用手动素材包交接，程序不会自动上传照片或调用生图服务。

## 安装

从 [Releases](https://github.com/Yhmx6/veylfit/releases) 下载 Windows x64 安装程序并核对SHA256。无需预装Python或MakeHuman。当前为小范围测试版、未签名；支持Windows 10/11 x64，更多设备兼容性仍需试用。

操作步骤见 [Windows使用说明](docs/Windows使用说明.md)。

## 流程

1. 填写基本资料，依次选择整体体型和四个部位；可选填胸、自然腰、腹、臀围、肩宽和腿内长。
2. 导入正侧全身照，检查照片标记，生成后台体型；查看填写值与模型值的差异。
3. 准备面部原照，手动生成并依次确认体型、正脸和侧脸，固定人物版本。
4. 选择真实衣物试穿或搭配推荐，导入衣物、选择效果、导出素材包。
5. 手动生成后导回，分别检查脸、身体和衣物，并保存历史。

人物原始数据与试衣任务快照分离；换衣不改变真实体型，修改人物资料会要求重新确认。

六项尺寸已经参与几何拟合，但对应模板近似位置，数值符合不代表真人扫描精度或服装尺码保证。当前模型路径仅验证成年男性；女性资料可保存草稿。多件套装、自由场景界面和自动生图尚未接入。

## 开发与构建

Windows x64、Python 3.12，建议独立虚拟环境：

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements-lock.txt
python src/veylfit/main.py
python -m unittest discover -s tests -v
python src/veylfit/main.py --self-test build/self-test.json
```

安装 Inno Setup 6 后：

```powershell
powershell -File packaging/build.ps1 -InnoCompiler "C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
```

程序产物在dist，安装包在release。许可证说明见 [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES.md)，通用资源有显式哈希清单。源代码公开查看，尚未另行授予开源再分发许可证。

## 文档与隐私

[产品与技术方案](docs/产品与技术方案.md) · [PRD](docs/PRD-产品需求文档.md) · [发布验收](docs/发布验收-0.2.0.md)

仓库及安装包不含真人照片、个人体型档案或固定人物模板。用户保存的档案可能含私密照片；上传交接包给生图服务由用户自行决定。系统同步目录可能自动同步文件。卸载不删除用户档案。

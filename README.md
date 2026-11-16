# NavigatorZH

为 Anaconda Navigator 提供简体中文界面的汉化工具。

NavigatorZH 主要翻译 Navigator 自身的菜单、按钮、设置项、弹窗和操作提示，让日常使用更方便。

目前适配 **Windows 上的 Anaconda Navigator 2.7.1 和 2.7.4**。其他版本尚未适配。

## 汉化范围

目前已经完成以下界面的主要汉化：

- 主页、环境管理、学习与社区
- 软件包管理及安装、更新、卸载操作
- 首选项与配置窗口
- 环境创建、导入、备份等操作
- 账户登录、日志查看器及常见提示窗口
- 2.7.4 新增的服务条款窗口及相关环境保护提示

软件包名称、应用名称、在线课程和文档内容等保留原文。

## 安装与使用

首先确认电脑安装的是受支持的 Anaconda Navigator 版本。

下载项目源码并解压，打开 **Anaconda Prompt**，进入 NavigatorZH 所在文件夹，并激活安装了目标 Navigator 的 Conda 环境。例如，安装在 `base` 时执行 `conda activate base`；如果 Navigator 装在其他环境，就激活相应环境。

**1. 检查兼容性**

```cmd
python main.py check
```

工具会自动识别当前环境中 Navigator 的版本，并检查已安装源码是否与该版本的汉化规则匹配。检查通过后再安装。

**2. 安装汉化**

关闭 Anaconda Navigator，执行：

```cmd
python main.py apply
```

安装完成后，重新打开 Navigator 即可使用中文界面。

**3. 查看安装状态**

```cmd
python main.py status
```

**4. 恢复英文**

关闭 Navigator，执行：

```cmd
python main.py restore
```

恢复完成后重新打开 Navigator。

## 注意事项

- 汉化会修改当前 Conda 环境中 Navigator 已安装的部分 Python 源码；安装前会自动保存原始文件。
- 请保留项目中的 `state/` 文件夹，里面包含安装记录和恢复用备份。多个 Conda 环境的记录会分别保存。
- 更新或重新安装 Navigator 前，建议先运行 `restore` 恢复原始文件。
- 同一个 Conda 环境的安装和恢复操作会互斥执行；若提示已有操作正在进行，请在该操作结束后重试。
- 如果 Navigator 源码被其他程序修改，工具会在写入前再次检查并拒绝覆盖；未完成恢复时会保留安装记录和备份，请勿删除 `state/`。
- 如果被汉化的源码文件被删除，恢复操作会停止并保留备份；需先修复原始安装文件后再尝试恢复。
- `check` 用于尚未汉化的版本；已安装汉化时可以用 `status` 检查状态。

## 项目开发

汉化内容和源码补丁分别保存在：

- `locales/zh_CN.json`：两种版本共用的中文翻译
- `patches/2.7.1.json`、`patches/2.7.4.json`：对应版本的补丁规则
- `core/engine.py`：安装、检查与恢复逻辑

新增或修改翻译时，可以使用 `tools/build_rules.py` 构建规则。

```cmd
python tools/build_rules.py validate
```

默认检查两个版本的规则结构、翻译完整性和共享语言包未使用的条目。仅检查某个版本时：

```cmd
python tools/build_rules.py validate --version 2.7.4
```

使用当前已激活的 Navigator 环境执行源码匹配与 Python 语法检查：

```cmd
python tools/build_rules.py verify
```

添加规则时使用 `python tools/build_rules.py add <规则草稿.json>`；规则将写入当前 Navigator 版本对应的补丁文件。`verify` 和 `add` 也可以使用 `--version` 显式指定版本，但指定版本必须与当前激活环境中安装的 Navigator 一致。

运行自动化测试：

```cmd
python -m unittest discover -s tests -v
```

欢迎反馈翻译问题、界面显示异常或兼容性问题。

## 关于项目

NavigatorZH 是一个独立的社区汉化项目，与 Anaconda 官方无关联。

Anaconda Navigator 及相关名称、标识归其各自权利人所有。

## 许可证

NavigatorZH 自行编写的代码采用 [MIT License](LICENSE)。
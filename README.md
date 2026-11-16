# NavigatorZH

为 Anaconda Navigator 提供简体中文界面的汉化工具。

NavigatorZH 主要翻译 Navigator 自身的菜单、按钮、设置项、弹窗和操作提示，让日常使用更方便。

目前适配 **Anaconda Navigator 2.7.1（Windows）**。其他版本暂未适配。

## 汉化范围

目前已经完成以下界面的主要汉化：

- 主页、环境管理、学习与社区
- 软件包管理及安装、更新、卸载操作
- 首选项与配置窗口
- 环境创建、导入、备份等操作
- 账户登录、日志查看器及常见提示窗口

软件包名称、应用名称、在线课程和文档内容等保留原文。

## 安装与使用

首先确保电脑上已经安装 Anaconda Navigator 2.7.1。

下载项目源码并解压，打开 **Anaconda Prompt**，进入 NavigatorZH 所在的文件夹。

如果 Navigator 安装在 `base` 环境，请先执行 `conda activate base`。

**1. 检查兼容性**

`python main.py check`

检查 Navigator 的版本及源码是否与汉化规则匹配。确认检查通过后，再继续安装。

**2. 安装汉化**

关闭 Anaconda Navigator，执行：

`python main.py apply`

安装完成后，重新打开 Navigator 即可使用中文界面。

**3. 查看安装状态**

`python main.py status`

**4. 恢复英文**

关闭 Navigator，执行：

`python main.py restore`

重新打开 Navigator 后，就会恢复原来的英文界面。

## 注意事项

- 目前只支持 Navigator 2.7.1，不同版本的源码可能存在差异。
- 汉化会修改 Navigator 已安装的部分 Python 源码。安装前会自动保存原始文件，方便之后恢复。
- 安装汉化后，请保留项目中的 `state/` 文件夹，里面存放着恢复原版所需的记录和备份。
- 更新或重新安装 Anaconda Navigator 前，建议先恢复英文版。
- 如果 Navigator 的源码已被其他程序修改，工具可能会拒绝应用或恢复补丁，避免覆盖已有改动。

## 项目开发

汉化内容和源码补丁分别保存在：

- `locales/zh_CN.json`：中文翻译
- `patches/2.7.1.json`：版本对应的补丁规则
- `core/engine.py`：安装、检查与恢复逻辑

新增或修改翻译时，可以使用 `tools/build_rules.py` 构建规则。

运行以下命令进行检查：

- `python tools/build_rules.py validate`：检查规则和翻译数据
- `python tools/build_rules.py verify`：检查源码匹配与生成后的 Python 语法
- `python -m unittest discover -s tests -v`：运行自动化测试

欢迎反馈翻译问题、界面显示异常或兼容性问题。

## 关于项目

NavigatorZH 是一个独立的社区汉化项目，与 Anaconda 官方无关联。

Anaconda Navigator 及相关名称、标识归其各自权利人所有。
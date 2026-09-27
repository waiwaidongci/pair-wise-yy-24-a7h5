# 电台播出与版权窗口排程

一个不依赖第三方包、使用 SQLite 和标准库 HTTP 服务的电台排程项目。系统把“计划排期”和“实际播出”分开保存，支持地区授权、日期窗口、禁播时段、节目冷却、赞助商间隔、直播临时替换、实播对账与版权越界检查。

## 运行

需要 Python 3.11+。

```bash
python app.py
```

默认端口为 `8111`，页面地址是 <http://127.0.0.1:8111>。第一次启动会创建 `radio.db` 并写入三条演示排期。也可以设置端口和数据库位置：

```bash
PORT=9000 RADIO_DB=/tmp/radio.db python app.py
```

## 测试

```bash
python -m unittest discover -s tests -v
```

测试覆盖完整流程：排期、临时替换、播放日志、按日期对账；同时覆盖时间重叠、未授权地区和实播错节目等失败场景。

## 主要 API

- `GET /api/state`：节目、排期和最近对账异常
- `POST /api/programs`：创建节目并授权地区
- `POST /api/programs/{id}/regions`：追加地区授权
- `POST /api/schedule`：创建排期
- `GET /api/slots/{id}/suggestions`：安全换播建议（候选按赞助/冷却剩余间隔排序，其余节目附不合适原因）
- `POST /api/slots/{id}/replace`：替换计划节目并重新校验
- `POST /api/playout`：登记实播记录
- `POST /api/reconcile`：按日期生成漏播、错播、时长偏差和超授权异常

准备排期时填写 `air_date`、`start_time`、`program_id`、`region`。页面会直接显示校验错误，不会保存失败的排期。

## 安全换播建议

临时停播时，在页面“安全换播建议”中输入尚未播出（`planned`）的排期 ID，系统会列出同日期、同地区、同时长的可替换节目，按赞助间隔和节目冷却的剩余富余从宽到紧排序（越靠前越安全）；其余节目逐条标明被版权授权、禁播时段、时间冲突、节目冷却、赞助规则或时长不符挡住的原因，冷却/赞助还会给出还差多少分钟。没有候选项时，页面会汇总是哪几类规则挡住了换播。编辑点击“采纳”后仍走现有的 `POST /api/slots/{id}/replace` 替换流程，整体校验不变。

# pxe_data 配置模板

`backend/pxe_data/` 目录含节点 MAC、BMC 地址与 BMC 凭据等敏感信息，**不入库**
（见仓库根目录 `.gitignore`）。

首次部署时：

```bash
mkdir -p backend/pxe_data
cp backend/pxe_data_example/nodes.json.example     backend/pxe_data/nodes.json
cp backend/pxe_data_example/pxe_host.json.example  backend/pxe_data/pxe_host.json
```

然后按实际集群修改 MAC、IP、主机名等字段。

## BMC 凭据

`pxe_host.json` 里的 `bmc_password` 默认为空。可以：

- 直接在 PXE 部署页面填写，或
- 通过环境变量注入，服务首次生成配置时会读取它：

```bash
export PXE_BMC_PASSWORD='your-bmc-password'
```

不要把真实密码提交进 git。

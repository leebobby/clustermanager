<template>
  <div class="diagnose-view">
    <!-- ══ 脚本配置全局操作栏 ══ -->
    <div class="scripts-mgmt-bar">
      <span class="bar-label">脚本配置</span>
      <div class="bar-actions">
        <el-tooltip content="将当前所有脚本导出为 JSON 文件" placement="bottom">
          <el-button size="small" @click="exportScripts">
            <el-icon><Download /></el-icon>&nbsp;导出配置
          </el-button>
        </el-tooltip>
        <el-tooltip content="从 JSON 文件导入脚本（按名称合并）" placement="bottom">
          <el-button size="small" @click="importFileRef.click()">
            <el-icon><Upload /></el-icon>&nbsp;导入配置
          </el-button>
        </el-tooltip>
        <input ref="importFileRef" type="file" accept=".json" style="display:none" @change="onImportFile" />

        <el-divider direction="vertical" />
        <el-tooltip content="把每个脚本导出成一个 .sh 文件（带 #@ 头），用 tab/分类 两级目录组织，便于 VSCode/git 管理复杂脚本" placement="bottom">
          <el-button size="small" @click="exportToDir" :loading="dirBusy">
            <el-icon><FolderOpened /></el-icon>&nbsp;导出到目录
          </el-button>
        </el-tooltip>
        <el-tooltip content="扫描目录下所有 .sh（按 tab/分类/名称合并导回）" placement="bottom">
          <el-button size="small" @click="importFromDir" :loading="dirBusy">
            <el-icon><FolderAdd /></el-icon>&nbsp;从目录导入
          </el-button>
        </el-tooltip>
        <el-tooltip :content="bundleInfo.exists
          ? `发布包: ${bundleInfo.count} 个脚本，更新于 ${formatDate(bundleInfo.mtime)}`
          : '尚未生成发布配置'" placement="bottom">
          <el-button size="small" type="primary" @click="saveBundle" :loading="savingBundle">
            <el-icon><Box /></el-icon>&nbsp;保存为发布配置
          </el-button>
        </el-tooltip>
        <el-tag v-if="bundleInfo.exists" size="small" type="success" class="bundle-tag">
          已有发布包 ({{ bundleInfo.count }} 脚本)
        </el-tag>
      </div>
    </div>

    <el-tabs v-model="activeTab" class="diag-tabs">

      <!-- ══════════════════════════════════════
           Tab 1: 业务诊断
      ══════════════════════════════════════ -->
      <el-tab-pane label="业务诊断" name="business">
        <div class="tab-toolbar">
          <el-button type="success" size="small" @click="openBatchDialog('business')">
            <el-icon><Stopwatch /></el-icon>&nbsp;一键体检
          </el-button>
          <el-divider direction="vertical" />
          <el-button type="primary" size="small" @click="openNewTypeDialog('business')">
            <el-icon><FolderAdd /></el-icon>&nbsp;新建诊断类型
          </el-button>
          <el-button size="small" @click="openScriptDialog(null, 'business')">
            <el-icon><Plus /></el-icon>&nbsp;新建脚本
          </el-button>
        </div>

        <div v-if="!businessCategories.length" class="empty-hint">
          暂无诊断类型，点击「新建诊断类型」开始
        </div>
        <div v-for="cat in businessCategories" :key="'biz-' + cat" class="category-section">
          <div class="category-header">
            <span class="cat-bullet">▣</span>{{ cat }}
          </div>
          <div class="script-grid">
            <div
              v-for="s in getScripts('business', cat)" :key="s.id"
              class="script-card" :class="{ 'script-card--disabled': !s.enabled }"
            >
              <div class="script-card-body">
                <div class="sc-name">{{ s.name }}</div>
                <div class="sc-desc">{{ s.description || '—' }}</div>
                <div class="sc-meta">
                  <el-tag size="small" type="info">{{ s.target_node_type }}</el-tag>
                  <span class="sc-timeout">{{ s.timeout }}s</span>
                </div>
              </div>
              <div class="script-card-footer">
                <el-button type="primary" size="small" :disabled="!s.enabled" @click="openRunDialog(s)">
                  <el-icon><VideoPlay /></el-icon> 运行
                </el-button>
                <el-button size="small" @click="openScriptDialog(s, 'business')">
                  <el-icon><Edit /></el-icon>
                </el-button>
                <el-button size="small" type="danger" @click="confirmDelete(s)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
            </div>
            <div v-if="!getScripts('business', cat).length" class="script-card-empty">
              <el-button text type="primary" @click="openScriptDialog(null, 'business', cat)">
                <el-icon><Plus /></el-icon> 添加脚本
              </el-button>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- ══════════════════════════════════════
           Tab 2: 硬件诊断
      ══════════════════════════════════════ -->
      <el-tab-pane label="硬件诊断" name="hardware">
        <div class="tab-toolbar">
          <el-button type="success" size="small" @click="openBatchDialog('hardware')">
            <el-icon><Stopwatch /></el-icon>&nbsp;一键体检
          </el-button>
          <el-divider direction="vertical" />
          <el-button type="primary" size="small" @click="openNewTypeDialog('hardware')">
            <el-icon><FolderAdd /></el-icon>&nbsp;新建诊断类型
          </el-button>
          <el-button size="small" @click="openScriptDialog(null, 'hardware')">
            <el-icon><Plus /></el-icon>&nbsp;新建脚本
          </el-button>
        </div>

        <div v-if="!hardwareCategories.length" class="empty-hint">
          暂无诊断类型，点击「新建诊断类型」开始
        </div>
        <div v-for="cat in hardwareCategories" :key="'hw-' + cat" class="category-section">
          <div class="category-header">
            <span class="cat-bullet">▣</span>{{ cat }}
          </div>
          <div class="script-grid">
            <div
              v-for="s in getScripts('hardware', cat)" :key="s.id"
              class="script-card" :class="{ 'script-card--disabled': !s.enabled }"
            >
              <div class="script-card-body">
                <div class="sc-name">{{ s.name }}</div>
                <div class="sc-desc">{{ s.description || '—' }}</div>
                <div class="sc-meta">
                  <el-tag size="small" type="info">{{ s.target_node_type }}</el-tag>
                  <span class="sc-timeout">{{ s.timeout }}s</span>
                </div>
              </div>
              <div class="script-card-footer">
                <el-button type="primary" size="small" :disabled="!s.enabled" @click="openRunDialog(s)">
                  <el-icon><VideoPlay /></el-icon> 运行
                </el-button>
                <el-button size="small" @click="openScriptDialog(s, 'hardware')">
                  <el-icon><Edit /></el-icon>
                </el-button>
                <el-button size="small" type="danger" @click="confirmDelete(s)">
                  <el-icon><Delete /></el-icon>
                </el-button>
              </div>
            </div>
            <div v-if="!getScripts('hardware', cat).length" class="script-card-empty">
              <el-button text type="primary" @click="openScriptDialog(null, 'hardware', cat)">
                <el-icon><Plus /></el-icon> 添加脚本
              </el-button>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- ══════════════════════════════════════
           Tab 3: 日志导出 (SSH 拉取目标主机日志到本机目录)
      ══════════════════════════════════════ -->
      <el-tab-pane label="日志导出" name="export">
        <el-card class="query-card">
          <el-form :model="exportForm" label-width="100px" :disabled="exporting">
            <el-row :gutter="16">
              <el-col :span="8">
                <el-form-item label="目标主机">
                  <el-input v-model="exportForm.target_host" placeholder="172.16.3.100" />
                </el-form-item>
              </el-col>
              <el-col :span="6">
                <el-form-item label="SSH 端口">
                  <el-input-number v-model="exportForm.ssh_port" :min="1" :max="65535"
                                   controls-position="right" style="width:100%" />
                </el-form-item>
              </el-col>
              <el-col :span="5">
                <el-form-item label="用户">
                  <el-input v-model="exportForm.ssh_user" placeholder="root" />
                </el-form-item>
              </el-col>
              <el-col :span="5">
                <el-form-item label="密码">
                  <el-input v-model="exportForm.ssh_password" type="password" show-password
                            placeholder="留空用已保存" />
                </el-form-item>
              </el-col>
            </el-row>
            <el-row :gutter="16">
              <el-col :span="14">
                <el-form-item label="输出目录">
                  <el-input v-model="exportForm.output_dir" placeholder="D:\logs\export">
                    <template #append>
                      <el-button @click="pickOutputDir" :loading="pickingFolder">
                        <el-icon><FolderOpened /></el-icon>&nbsp;浏览
                      </el-button>
                    </template>
                  </el-input>
                  <div class="run-ip-hint">不存在会自动创建; 浏览按钮调系统原生目录选择</div>
                </el-form-item>
              </el-col>
              <el-col :span="10">
                <el-form-item label="告警时间">
                  <el-date-picker
                    v-model="exportForm.alert_time" type="datetime"
                    placeholder="可选, 启用脚本时间窗"
                    style="width:200px"
                    value-format="YYYY-MM-DDTHH:mm:ss"
                  />
                  <el-button v-if="exportForm.alert_time" link size="small" type="info"
                             style="margin-left:6px" @click="exportForm.alert_time = null">清除</el-button>
                </el-form-item>
              </el-col>
            </el-row>
            <el-row v-if="exportForm.alert_time" :gutter="16">
              <el-col :span="24">
                <el-form-item label="时间窗 (分)">
                  <span class="range-label">前</span>
                  <el-input-number v-model="exportForm.range_before_min" :min="0" :max="1440"
                                   size="small" controls-position="right" style="width:110px" />
                  <span class="range-label">分 · 后</span>
                  <el-input-number v-model="exportForm.range_after_min"  :min="0" :max="1440"
                                   size="small" controls-position="right" style="width:110px" />
                  <span class="range-label">分</span>
                  <span class="run-ip-hint" style="display:inline-block;margin-left:10px">
                    脚本里可用 <code>$ALERT_TIME</code> / <code>$ALERT_FROM</code> / <code>$ALERT_TO</code>
                  </span>
                </el-form-item>
              </el-col>
            </el-row>
          </el-form>
        </el-card>

        <!-- 脚本选择: 按 category 分组, 每个 category 内多脚本可选, 可编辑/新增 -->
        <el-card class="result-card">
          <template #header>
            <div class="card-header">
              <span>采集脚本 (按类型分组)</span>
              <div>
                <el-button size="small" @click="openScriptDialog(null, 'log_export')">
                  <el-icon><Plus /></el-icon>&nbsp;新建采集脚本
                </el-button>
                <el-button size="small" type="primary" @click="openNewTypeDialog('log_export')">
                  <el-icon><FolderAdd /></el-icon>&nbsp;新建类型
                </el-button>
              </div>
            </div>
          </template>

          <div v-if="!exportCategories.length" class="empty-hint">
            暂无采集脚本, 点「新建类型」或「新建采集脚本」开始
          </div>

          <div v-for="cat in exportCategories" :key="'exp-' + cat" class="category-section">
            <div class="category-header">
              <span class="cat-bullet">▣</span>{{ cat }}
              <el-checkbox
                :model-value="isCatAllChecked(cat)"
                :indeterminate="isCatIndeterminate(cat)"
                @change="toggleCatAll(cat, $event)"
                style="margin-left: 12px"
              >全选</el-checkbox>
            </div>
            <div class="script-grid">
              <div
                v-for="s in getScripts('log_export', cat)" :key="s.id"
                class="script-card"
                :class="{ 'script-card--selected': exportForm.script_ids.includes(s.id) }"
              >
                <div class="script-card-body">
                  <el-checkbox
                    :model-value="exportForm.script_ids.includes(s.id)"
                    @change="toggleScript(s.id, $event)"
                  >
                    <span class="sc-name">{{ s.name }}</span>
                  </el-checkbox>
                  <div class="sc-desc" style="margin-top:4px">{{ s.description || '—' }}</div>
                  <div class="sc-meta">
                    <el-tag
                      size="small"
                      :type="(s.output_mode || 'stdout') === 'files' ? 'success' : 'info'"
                    >
                      {{ (s.output_mode || 'stdout') === 'files' ? 'SFTP 完整文件' : 'stdout 落盘' }}
                    </el-tag>
                    <span class="sc-timeout">超时 {{ s.timeout }}s</span>
                  </div>
                </div>
                <div class="script-card-footer">
                  <el-button size="small" @click="openScriptDialog(s, 'log_export')">
                    <el-icon><Edit /></el-icon> 编辑
                  </el-button>
                  <el-button size="small" type="danger" @click="confirmDelete(s)">
                    <el-icon><Delete /></el-icon>
                  </el-button>
                </div>
              </div>
              <div v-if="!getScripts('log_export', cat).length" class="script-card-empty">
                <el-button text type="primary" @click="openScriptDialog(null, 'log_export', cat)">
                  <el-icon><Plus /></el-icon> 添加脚本
                </el-button>
              </div>
            </div>
          </div>
        </el-card>

        <!-- 执行栏 -->
        <el-card class="result-card">
          <template #header>
            <div class="card-header">
              <span>导出执行</span>
              <el-tag v-if="exportResults.length" type="info" size="small">
                已完成 {{ exportResults.length }} / {{ exportProgress.total || '?' }}
              </el-tag>
            </div>
          </template>

          <div class="run-action-bar">
            <el-button
              v-if="!exporting"
              type="primary"
              @click="startExport"
              :disabled="!exportForm.script_ids.length || !exportForm.target_host || !exportForm.output_dir"
            >
              <el-icon><Download /></el-icon>&nbsp;开始导出 ({{ exportForm.script_ids.length }} 个脚本)
            </el-button>
            <el-button
              v-else type="danger"
              :loading="cancellingExport"
              @click="terminateExport"
            >
              <el-icon><CircleClose /></el-icon>&nbsp;终止
            </el-button>
            <span v-if="exportRunId" class="run-id-tag">run: {{ exportRunId }}</span>
            <span v-if="exportProgress.output_dir" class="run-progress">
              落盘目录: <code>{{ exportProgress.output_dir }}</code>
            </span>
          </div>

          <el-empty v-if="!exportResults.length && !exporting"
                    description="勾选脚本后点击「开始导出」" :image-size="60" />

          <el-table v-else :data="exportResults" size="small" max-height="360" stripe>
            <el-table-column prop="category" label="类型" width="100">
              <template #default="{ row }">
                <el-tag size="small">{{ row.category }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="name" label="脚本" width="170" show-overflow-tooltip />
            <el-table-column label="模式" width="100">
              <template #default="{ row }">
                <el-tag size="small" :type="row.mode === 'files' ? 'success' : 'info'">
                  {{ row.mode === 'files' ? 'files' : 'stdout' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="row.success ? 'success' : 'danger'" size="small">
                  {{ row.success ? '成功' : `失败 (${row.exit_code})` }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="大小" width="90">
              <template #default="{ row }">
                {{ row.size != null ? `${(row.size/1024).toFixed(1)} KB` : '—' }}
              </template>
            </el-table-column>
            <el-table-column prop="remote" label="远端路径" width="200" show-overflow-tooltip>
              <template #default="{ row }">
                <code v-if="row.remote" style="color:#79c0ff">{{ row.remote }}</code>
                <span v-else style="color:#5a7090">—</span>
              </template>
            </el-table-column>
            <el-table-column prop="file" label="本地落盘路径" show-overflow-tooltip />
          </el-table>
        </el-card>
      </el-tab-pane>
    </el-tabs>

    <!-- ══ 新建诊断类型 ══ -->
    <el-dialog v-model="newTypeDialog.visible" title="新建诊断类型" width="420px">
      <el-form label-width="90px">
        <el-form-item label="类型名称">
          <el-input
            v-model="newTypeDialog.name"
            placeholder="如: 性能诊断"
            @keyup.enter="confirmNewType"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="newTypeDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="confirmNewType">创建</el-button>
      </template>
    </el-dialog>

    <!-- ══ 脚本新建/编辑 ══ -->
    <el-dialog
      v-model="scriptDialog.visible"
      :title="scriptDialog.editing ? '编辑脚本' : '新建脚本'"
      width="700px"
    >
      <el-form :model="scriptForm" label-width="90px">
        <el-form-item label="脚本名称" required>
          <el-input v-model="scriptForm.name" placeholder="简短描述该诊断项" />
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="14">
            <el-form-item label="所属分类">
              <el-autocomplete
                v-model="scriptForm.category"
                :fetch-suggestions="suggestCats"
                placeholder="选择或输入分类"
                style="width:100%"
              />
            </el-form-item>
          </el-col>
          <el-col :span="10">
            <el-form-item label="节点类型">
              <el-select v-model="scriptForm.target_node_type" style="width:100%">
                <el-option label="所有节点" value="all" />
                <el-option label="Master" value="master" />
                <el-option label="Slave" value="slave" />
                <el-option label="Sensor" value="sensor" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="描述">
          <el-input v-model="scriptForm.description" type="textarea" :rows="2" placeholder="可选" />
        </el-form-item>
        <el-form-item label="脚本内容" required>
          <el-input
            v-model="scriptForm.script_content"
            type="textarea" :rows="10"
            class="code-textarea"
            placeholder="输入 SSH 命令或 shell 脚本，将在目标节点上远程执行"
          />
          <div class="import-hint">
            <input
              ref="fileInputRef" type="file"
              style="display:none" accept=".sh,.py,.bash,.txt"
              @change="onFileImport"
            />
            <el-button text type="primary" size="small" @click="fileInputRef.click()">
              <el-icon><Upload /></el-icon> 导入本地脚本文件
            </el-button>
          </div>
        </el-form-item>
        <el-row :gutter="12">
          <el-col :span="12">
            <el-form-item label="超时(秒)">
              <el-input-number v-model="scriptForm.timeout" :min="5" :max="600" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="启用">
              <el-switch v-model="scriptForm.enabled" />
            </el-form-item>
          </el-col>
        </el-row>

        <!-- 判定规则: 仅 business/hardware 诊断脚本用, 把"跑命令"升级成"判结论" -->
        <template v-if="scriptForm.script_tab !== 'log_export'">
          <el-form-item label="结果判定">
            <el-select v-model="scriptForm.expect_mode" style="width:100%">
              <el-option label="按退出码 (exit 0 = 正常, 否则异常)" value="exit_code" />
              <el-option label="命中关键字/正则 → 判异常 (如 error|fail|panic)" value="fault_if_match" />
              <el-option label="命中关键字/正则 → 判正常 (如 active (running))" value="pass_if_match" />
            </el-select>
          </el-form-item>
          <el-form-item v-if="scriptForm.expect_mode !== 'exit_code'" label="关键字/正则">
            <el-input v-model="scriptForm.expect_pattern"
                      placeholder="对 stdout+stderr 做匹配, 大小写不敏感; 支持正则" />
            <div class="run-ip-hint">
              {{ scriptForm.expect_mode === 'fault_if_match'
                 ? '输出里出现该模式即判「异常」, 例: error|timeout|panic'
                 : '输出里必须出现该模式才判「正常」, 没出现即「异常」, 例: active \\(running\\)' }}
            </div>
          </el-form-item>
          <el-form-item label="处置建议">
            <el-input v-model="scriptForm.suggestion" type="textarea" :rows="2"
                      placeholder="可选; 判为异常时显示在体检报告里, 指导运维如何处理" />
          </el-form-item>
        </template>

        <!-- 仅日志导出脚本支持 output_mode: stdout 把 stdout 落一个文件; files 用 SFTP 拉完整文件 -->
        <el-form-item v-if="scriptForm.script_tab === 'log_export'" label="输出模式">
          <el-radio-group v-model="scriptForm.output_mode">
            <el-radio-button value="stdout">stdout 落盘</el-radio-button>
            <el-radio-button value="files">SFTP 完整文件</el-radio-button>
          </el-radio-group>
          <div class="run-ip-hint">
            <b v-if="scriptForm.output_mode === 'files'">files</b><b v-else>stdout</b>:
            <span v-if="scriptForm.output_mode === 'files'">
              脚本 stdout 当作待下载路径清单 (一行一个绝对路径), 后端 SFTP 完整拉回。
              适合需要保留完整日志、避免筛选命令漏行的场景。空行 / # 注释行忽略。
            </span>
            <span v-else>
              脚本 stdout 直接写到一个 .log 文件 (默认)。超过 50KB 会被截断, 适合摘要或小输出。
            </span>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="scriptDialog.visible = false">取消</el-button>
        <el-button type="primary" @click="saveScript" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- ══ 运行脚本 ══ -->
    <el-dialog
      v-model="runDialog.visible"
      :title="`运行: ${runDialog.script?.name}`"
      width="780px"
      :close-on-click-modal="!running"
      :close-on-press-escape="!running"
      :show-close="!running"
      @closed="onRunDialogClosed"
    >
      <el-alert
        v-if="running"
        type="warning" :closable="false" show-icon
        title="正在执行, 对话框已锁定. 点「终止」可强制中断 (会关闭所有正在进行的 SSH)"
        style="margin-bottom:14px"
      />
      <el-form :model="runForm" label-width="86px" class="run-form-block" :disabled="running">
        <!-- 模式切换 -->
        <el-form-item label="目标方式">
          <el-radio-group v-model="runForm.target_mode" size="small">
            <el-radio-button value="ips">手动 IP</el-radio-button>
            <el-radio-button value="nodes">节点选择</el-radio-button>
          </el-radio-group>
        </el-form-item>

        <!-- 目标值 -->
        <el-form-item :label="runForm.target_mode === 'ips' ? '目标 IP' : '目标节点'">
          <el-input
            v-if="runForm.target_mode === 'ips'"
            v-model="runForm.manual_ips"
            style="width:360px"
            placeholder="172.16.3.100（多个用英文逗号分隔）"
          />
          <el-select
            v-else
            v-model="runForm.node_ids" multiple collapse-tags
            style="width:360px" placeholder="选择节点（含离线）"
          >
            <el-option
              v-for="n in nodes" :key="n.id"
              :label="`${n.hostname} (${n.ctrl_ip || n.mgmt_ip || '无IP'}) [${n.status}]`"
              :value="n.id"
            />
          </el-select>
          <div v-if="runForm.target_mode === 'ips'" class="run-ip-hint">
            SSH 将直接连到此 IP, 不依赖节点管理
          </div>
        </el-form-item>

        <!-- 凭据 + 端口 -->
        <el-form-item label="SSH 凭据">
          <el-input v-model="runForm.ssh_user" placeholder="用户名" style="width:120px" />
          <el-input v-model="runForm.ssh_password" type="password" show-password
                    placeholder="密码" style="width:160px;margin-left:8px" />
          <el-input v-model.number="runForm.ssh_port" type="number" min="1" max="65535"
                    placeholder="端口" style="width:90px;margin-left:8px" />
        </el-form-item>

        <!-- 故障时间窗 (可选): 脚本里可直接读 $ALERT_TIME / $ALERT_FROM / $ALERT_TO -->
        <el-form-item label="告警时间">
          <el-date-picker
            v-model="runForm.alert_time"
            type="datetime"
            placeholder="可选, 留空表示不限时间"
            style="width:240px"
            value-format="YYYY-MM-DDTHH:mm:ss"
          />
          <el-button
            v-if="runForm.alert_time" size="small" link type="info"
            style="margin-left:6px" @click="runForm.alert_time = null"
          >清除</el-button>
        </el-form-item>
        <el-form-item label="查询范围" v-if="runForm.alert_time">
          <span class="range-label">前</span>
          <el-input-number v-model="runForm.range_before_min" :min="0" :max="1440"
                           size="small" controls-position="right" style="width:110px" />
          <span class="range-label">分 · 后</span>
          <el-input-number v-model="runForm.range_after_min"  :min="0" :max="1440"
                           size="small" controls-position="right" style="width:110px" />
          <span class="range-label">分</span>
          <div class="run-ip-hint">
            脚本可用变量 <code>$ALERT_TIME</code> / <code>$ALERT_FROM</code> / <code>$ALERT_TO</code>
            (格式 <code>YYYY-MM-DD HH:MM:SS</code>) 给 journalctl --since/--until 或 dmesg 用
          </div>
        </el-form-item>
      </el-form>

      <pre class="script-preview">{{ runDialog.script?.script_content }}</pre>

      <div class="run-action-bar">
        <el-button
          v-if="!running"
          type="primary"
          @click="executeScript"
          :disabled="runForm.target_mode === 'nodes' ? !runForm.node_ids.length : !runForm.manual_ips.trim()"
        >
          <el-icon><VideoPlay /></el-icon>&nbsp;执行
        </el-button>
        <el-button
          v-else
          type="danger"
          :loading="cancelling"
          @click="terminateRun"
        >
          <el-icon><CircleClose /></el-icon>&nbsp;终止
        </el-button>
        <el-tag v-if="credsLoaded" size="small" type="success">
          已保存凭据 ({{ runForm.ssh_user }})
        </el-tag>
        <span v-if="runProgress.total" class="run-progress">
          已完成 {{ runResults.length }} / {{ runProgress.total }}
        </span>
        <span v-if="currentRunId" class="run-id-tag">run: {{ currentRunId }}</span>
      </div>

      <div v-for="res in runResults" :key="res.node_id ?? res.host" class="run-result">
        <div class="run-result-title">
          <span>
            {{ res.hostname }}
            <span class="run-host">{{ res.host || '—' }}</span>
          </span>
          <span class="run-verdict-tags">
            <el-tag size="small" effect="dark" :type="verdictMeta(res.verdict).type">
              {{ verdictMeta(res.verdict).label }}
            </el-tag>
            <el-tag size="small" type="info" effect="plain">exit {{ res.exit_code }}</el-tag>
          </span>
        </div>
        <div v-if="res.verdict === 'fail' && res.suggestion" class="run-suggestion">
          <el-icon><WarningFilled /></el-icon>&nbsp;处置建议：{{ res.suggestion }}
        </div>
        <pre class="run-stdout">{{ res.stdout || '(无输出)' }}</pre>
        <pre v-if="res.stderr" class="run-stderr">{{ res.stderr }}</pre>
      </div>
    </el-dialog>

    <!-- ══ 一键体检: 一组目标 × 一组脚本 并发执行 + 汇总报告 ══ -->
    <el-dialog
      v-model="batchDialog.visible"
      :title="`一键体检 — ${batchDialog.tab === 'business' ? '业务诊断' : '硬件诊断'}`"
      width="900px"
      :close-on-click-modal="!batchRunning"
      :close-on-press-escape="!batchRunning"
      :show-close="!batchRunning"
      @closed="onBatchDialogClosed"
    >
      <el-alert
        v-if="batchRunning" type="warning" :closable="false" show-icon
        title="体检进行中, 对话框已锁定. 点「终止」可强制中断所有 SSH"
        style="margin-bottom:14px"
      />

      <el-form :model="batchForm" label-width="86px" :disabled="batchRunning">
        <el-form-item label="目标方式">
          <el-radio-group v-model="batchForm.target_mode" size="small">
            <el-radio-button value="ips">手动 IP</el-radio-button>
            <el-radio-button value="nodes">节点选择</el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item :label="batchForm.target_mode === 'ips' ? '目标 IP' : '目标节点'">
          <el-input
            v-if="batchForm.target_mode === 'ips'"
            v-model="batchForm.manual_ips" style="width:420px"
            placeholder="172.16.3.100（多个用英文逗号分隔）"
          />
          <el-select
            v-else v-model="batchForm.node_ids" multiple collapse-tags
            style="width:420px" placeholder="选择节点（含离线）"
          >
            <el-option
              v-for="n in nodes" :key="n.id"
              :label="`${n.hostname} (${n.ctrl_ip || n.mgmt_ip || '无IP'}) [${n.status}]`"
              :value="n.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="检查范围">
          <el-select v-model="batchForm.category" style="width:240px" clearable placeholder="全部分类">
            <el-option label="全部分类" value="" />
            <el-option v-for="c in batchCategories" :key="c" :label="c" :value="c" />
          </el-select>
          <span class="run-ip-hint" style="margin-left:10px">
            将执行 {{ batchScriptCount }} 个启用脚本 × {{ batchTargetCount }} 个目标
          </span>
        </el-form-item>
        <el-form-item label="SSH 凭据">
          <el-input v-model="batchForm.ssh_user" placeholder="用户名" style="width:120px" />
          <el-input v-model="batchForm.ssh_password" type="password" show-password
                    placeholder="密码" style="width:160px;margin-left:8px" />
          <el-input v-model.number="batchForm.ssh_port" type="number" min="1" max="65535"
                    placeholder="端口" style="width:90px;margin-left:8px" />
          <el-tag v-if="batchCredsLoaded" size="small" type="success" style="margin-left:8px">
            已保存凭据
          </el-tag>
        </el-form-item>
        <el-form-item label="告警时间">
          <el-date-picker
            v-model="batchForm.alert_time" type="datetime"
            placeholder="可选, 留空表示不限时间" style="width:240px"
            value-format="YYYY-MM-DDTHH:mm:ss"
          />
          <el-button v-if="batchForm.alert_time" size="small" link type="info"
                     style="margin-left:6px" @click="batchForm.alert_time = null">清除</el-button>
        </el-form-item>
        <el-form-item label="查询范围" v-if="batchForm.alert_time">
          <span class="range-label">前</span>
          <el-input-number v-model="batchForm.range_before_min" :min="0" :max="1440"
                           size="small" controls-position="right" style="width:110px" />
          <span class="range-label">分 · 后</span>
          <el-input-number v-model="batchForm.range_after_min" :min="0" :max="1440"
                           size="small" controls-position="right" style="width:110px" />
          <span class="range-label">分</span>
        </el-form-item>
      </el-form>

      <div class="run-action-bar">
        <el-button
          v-if="!batchRunning" type="success" @click="executeBatch"
          :disabled="(batchForm.target_mode === 'nodes' ? !batchForm.node_ids.length : !batchForm.manual_ips.trim()) || !batchScriptCount"
        >
          <el-icon><Stopwatch /></el-icon>&nbsp;开始体检
        </el-button>
        <el-button v-else type="danger" :loading="batchCancelling" @click="terminateBatch">
          <el-icon><CircleClose /></el-icon>&nbsp;终止
        </el-button>
        <span v-if="batchProgress.total" class="run-progress">
          已完成 {{ batchResults.length }} / {{ batchProgress.total }}
        </span>
        <span v-if="batchRunId" class="run-id-tag">run: {{ batchRunId }}</span>
      </div>

      <!-- 体检报告: 健康度统计 + 结果(异常置顶) -->
      <template v-if="batchResults.length">
        <div class="report-stats">
          <div class="stat-chip stat-total">检查项 <b>{{ batchResults.length }}</b></div>
          <div class="stat-chip stat-pass">正常 <b>{{ batchCounts.pass }}</b></div>
          <div class="stat-chip stat-fail">异常 <b>{{ batchCounts.fail }}</b></div>
          <div class="stat-chip stat-error">错误 <b>{{ batchCounts.error }}</b></div>
          <div class="report-health" :class="`health-${batchHealthLevel}`">
            健康度 {{ batchHealthScore }}%
          </div>
        </div>

        <el-table :data="sortedBatchResults" size="small" max-height="380" stripe
                  :row-class-name="batchRowClass">
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="report-expand">
                <div v-if="row.suggestion" class="run-suggestion" style="border:none">
                  <el-icon><WarningFilled /></el-icon>&nbsp;处置建议：{{ row.suggestion }}
                </div>
                <pre class="run-stdout">{{ row.stdout || '(无输出)' }}</pre>
                <pre v-if="row.stderr" class="run-stderr">{{ row.stderr }}</pre>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="判定" width="80">
            <template #default="{ row }">
              <el-tag size="small" effect="dark" :type="verdictMeta(row.verdict).type">
                {{ verdictMeta(row.verdict).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="category" label="类型" width="110" show-overflow-tooltip />
          <el-table-column prop="script_name" label="检查项" width="180" show-overflow-tooltip />
          <el-table-column label="节点" width="180" show-overflow-tooltip>
            <template #default="{ row }">
              {{ row.hostname }}<span class="run-host">{{ row.host || '—' }}</span>
            </template>
          </el-table-column>
          <el-table-column label="结论 / 建议" show-overflow-tooltip>
            <template #default="{ row }">
              <span v-if="row.verdict === 'fail'" class="report-sug">{{ row.suggestion || '命中异常判定规则，展开查看输出' }}</span>
              <span v-else-if="row.verdict === 'error'" class="report-err">{{ row.stderr || '执行错误' }}</span>
              <span v-else class="report-ok">正常</span>
            </template>
          </el-table-column>
        </el-table>
      </template>
      <el-empty v-else-if="!batchRunning" description="选择目标后点「开始体检」" :image-size="60" />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

// ─── 节点 ───
const nodes = ref([])

// ─── Tab ───
const activeTab = ref('business')

// ─── 脚本数据 ───
const scripts = ref([])

function getScripts(tab, cat) {
  return scripts.value.filter(s => s.script_tab === tab && s.category === cat)
}

// ─── 分类管理 ───
const DEFAULT_CATS = {
  business: ['初始化', '检测流程', 'LT流程', 'PDA流程'],
  hardware: ['存储诊断', '设备诊断', '网络诊断', '系统诊断'],
  log_export: ['business', 'system', 'kernel', 'network'],
}

function loadUserCats(tab) {
  try { return JSON.parse(localStorage.getItem(`diag_cats_${tab}`) || '[]') } catch { return [] }
}
function saveUserCats(tab, list) {
  localStorage.setItem(`diag_cats_${tab}`, JSON.stringify(list))
}

const userBusinessCats   = ref(loadUserCats('business'))
const userHardwareCats   = ref(loadUserCats('hardware'))
const userLogExportCats  = ref(loadUserCats('log_export'))

const businessCategories = computed(() => {
  const fromScripts = scripts.value.filter(s => s.script_tab === 'business').map(s => s.category)
  return [...new Set([...DEFAULT_CATS.business, ...userBusinessCats.value, ...fromScripts])]
})
const hardwareCategories = computed(() => {
  const fromScripts = scripts.value.filter(s => s.script_tab === 'hardware').map(s => s.category)
  return [...new Set([...DEFAULT_CATS.hardware, ...userHardwareCats.value, ...fromScripts])]
})
const exportCategories   = computed(() => {
  const fromScripts = scripts.value.filter(s => s.script_tab === 'log_export').map(s => s.category)
  return [...new Set([...DEFAULT_CATS.log_export, ...userLogExportCats.value, ...fromScripts])]
})

// ─── 新建类型 ───
const newTypeDialog = ref({ visible: false, name: '', tab: 'business' })

function openNewTypeDialog(tab) {
  newTypeDialog.value = { visible: true, name: '', tab }
}
function confirmNewType() {
  const name = newTypeDialog.value.name.trim()
  if (!name) { ElMessage.warning('请输入类型名称'); return }
  const tab = newTypeDialog.value.tab
  const buckets = {
    business:   { list: userBusinessCats,  all: businessCategories  },
    hardware:   { list: userHardwareCats,  all: hardwareCategories  },
    log_export: { list: userLogExportCats, all: exportCategories    },
  }
  const b = buckets[tab]
  if (b && !b.all.value.includes(name)) {
    b.list.value.push(name)
    saveUserCats(tab, b.list.value)
  }
  ElMessage.success(`已创建「${name}」`)
  newTypeDialog.value.visible = false
}

// ─── 脚本 CRUD ───
const scriptDialog = ref({ visible: false, editing: null, tab: 'business' })
const saving = ref(false)
const fileInputRef = ref(null)

function defaultForm(tab = 'business', cat = '') {
  const defaultCat = DEFAULT_CATS[tab]?.[0] || ''
  return {
    name: '', description: '',
    script_tab: tab,
    category: cat || defaultCat,
    script_content: '', target_node_type: 'all',
    timeout: tab === 'log_export' ? 60 : 30,
    enabled: true,
    output_mode: 'stdout',
    expect_mode: 'exit_code',
    expect_pattern: '',
    suggestion: '',
  }
}
const scriptForm = ref(defaultForm())

function openScriptDialog(script, tab, presetCat = '') {
  scriptDialog.value = { visible: true, editing: script, tab }
  scriptForm.value = script ? { ...script } : defaultForm(tab, presetCat)
}

function suggestCats(query, cb) {
  const t = scriptDialog.value.tab
  const cats = t === 'business'    ? businessCategories.value
            : t === 'log_export'   ? exportCategories.value
            : hardwareCategories.value
  cb(cats.filter(c => c.includes(query || '')).map(c => ({ value: c })))
}

function onFileImport(event) {
  const file = event.target.files[0]
  if (!file) return
  const reader = new FileReader()
  reader.onload = e => {
    scriptForm.value.script_content = e.target.result
    ElMessage.success(`已导入: ${file.name}`)
  }
  reader.readAsText(file, 'utf-8')
  event.target.value = ''
}

async function saveScript() {
  if (!scriptForm.value.name.trim() || !scriptForm.value.script_content.trim()) {
    ElMessage.warning('脚本名称和内容不能为空')
    return
  }
  saving.value = true
  try {
    if (scriptDialog.value.editing) {
      await axios.put(`/api/diagnose/scripts/${scriptDialog.value.editing.id}`, scriptForm.value)
      ElMessage.success('更新成功')
    } else {
      await axios.post('/api/diagnose/scripts', scriptForm.value)
      ElMessage.success('创建成功')
    }
    scriptDialog.value.visible = false
    loadScripts()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

async function confirmDelete(script) {
  try {
    await ElMessageBox.confirm(`确定删除「${script.name}」？`, '删除确认', {
      type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消'
    })
    await axios.delete(`/api/diagnose/scripts/${script.id}`)
    ElMessage.success('已删除')
    loadScripts()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error('删除失败')
  }
}

// ─── 三态判定元信息 ───
const VERDICT_META = {
  pass:  { label: '正常', type: 'success' },
  fail:  { label: '异常', type: 'danger' },
  error: { label: '错误', type: 'info' },
}
function verdictMeta(v) {
  return VERDICT_META[v] || { label: v || '—', type: 'info' }
}

// ─── 运行脚本 (流式 SSE + 凭据持久化 + 可终止) ───
const PWD_MASK = '********'
const runDialog = ref({ visible: false, script: null })
const runForm = ref({
  target_mode: 'ips',           // 默认手动 IP 模式（无在线节点时也能用）
  node_ids: [],
  manual_ips: '172.16.3.100',   // 默认控制面 IP
  ssh_user: 'root',
  ssh_password: '',
  ssh_port: 22,
  // 故障时间窗 (可选)
  alert_time: null,
  range_before_min: 5,
  range_after_min: 10,
})
const running = ref(false)
const cancelling = ref(false)
const currentRunId = ref('')
const runResults = ref([])
const runProgress = ref({ total: 0 })
const credsLoaded = ref(false)

// 只有 status === 'online' 的节点可作为脚本执行目标 (SSH 走 ctrl_ip)
const onlineNodes = computed(() => nodes.value.filter(n => n.status === 'online'))

async function loadSavedCreds() {
  try {
    const res = await axios.get('/api/diagnose/ssh-creds')
    if (res.data.has_saved) {
      runForm.value.ssh_user = res.data.ssh_user || 'root'
      runForm.value.ssh_port = res.data.ssh_port || 22
      runForm.value.ssh_password = PWD_MASK    // 占位符, 提交时后端会用已保存的真密码
      credsLoaded.value = true
    } else {
      credsLoaded.value = false
    }
  } catch {
    credsLoaded.value = false
  }
}

function openRunDialog(script) {
  runDialog.value = { visible: true, script }
  runResults.value = []
  runProgress.value = { total: 0 }
  currentRunId.value = ''
  loadSavedCreds()
  loadNodes()        // 拉最新节点状态, 仅在线节点可选
}

function onRunDialogClosed() {
  runResults.value = []
  currentRunId.value = ''
  // 若用户在 running 中强行尝试关 (理论上 show-close 已禁用), 安全兜底
  running.value = false
  cancelling.value = false
}

async function executeScript() {
  // 构造请求体：按模式取 node_ids 或 target_ips
  const payload = {
    node_ids: runForm.value.target_mode === 'nodes' ? runForm.value.node_ids : [],
    target_ips: runForm.value.target_mode === 'ips'
      ? runForm.value.manual_ips.split(',').map(s => s.trim()).filter(Boolean)
      : [],
    ssh_user: runForm.value.ssh_user,
    ssh_password: runForm.value.ssh_password,
    ssh_port: Number(runForm.value.ssh_port) || 22,
    alert_time: runForm.value.alert_time || null,
    range_before_min: Number(runForm.value.range_before_min) || 0,
    range_after_min:  Number(runForm.value.range_after_min)  || 0,
  }
  if (!payload.node_ids.length && !payload.target_ips.length) {
    ElMessage.warning('请选择节点或填写目标 IP')
    return
  }
  running.value = true
  cancelling.value = false
  currentRunId.value = ''
  runResults.value = []
  runProgress.value = { total: 0 }

  try {
    const resp = await fetch(`/api/diagnose/scripts/${runDialog.value.script.id}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`
      try { detail = (await resp.json()).detail || detail } catch {}
      throw new Error(detail)
    }

    // 解析 SSE 数据流: 每事件 `data: {...}\n\n`
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let endEvent = null

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buf.indexOf('\n\n')) !== -1) {
        const chunk = buf.slice(0, idx).trim()
        buf = buf.slice(idx + 2)
        if (!chunk.startsWith('data:')) continue
        const json = chunk.replace(/^data:\s*/, '')
        if (!json) continue
        let evt
        try { evt = JSON.parse(json) } catch { continue }

        if (evt.type === 'start') {
          runProgress.value = { total: evt.total }
          currentRunId.value = evt.run_id || ''
        } else if (evt.type === 'result') {
          runResults.value.push(evt)        // 增量追加, 实时显示
        } else if (evt.type === 'end') {
          endEvent = evt
        }
      }
    }

    const total  = endEvent?.total  ?? runResults.value.length
    const passed = endEvent?.passed ?? runResults.value.filter(r => r.verdict === 'pass').length
    const failed = endEvent?.failed ?? runResults.value.filter(r => r.verdict === 'fail').length
    const errored = endEvent?.errored ?? runResults.value.filter(r => r.verdict === 'error').length
    const summary = `正常 ${passed} · 异常 ${failed} · 错误 ${errored} (共 ${total})`
    if (endEvent?.cancelled) {
      ElMessage.warning(`已终止: ${summary}`)
    } else {
      ElMessage[(failed === 0 && errored === 0) ? 'success' : 'warning'](`执行完成: ${summary}`)
    }

    // 凭据持久化: 仅当用户实际输入了新密码时, 后端会自动保存
    // 这里再拉一次状态以更新标签
    if (runForm.value.ssh_password && runForm.value.ssh_password !== PWD_MASK) {
      loadSavedCreds()
    }
  } catch (e) {
    ElMessage.error(e.message || '执行失败')
  } finally {
    running.value = false
    cancelling.value = false
    currentRunId.value = ''
  }
}

async function terminateRun() {
  if (!currentRunId.value || cancelling.value) return
  try {
    await ElMessageBox.confirm(
      '强制终止会立刻关闭所有正在进行的 SSH 连接, 已完成的节点结果会保留, 进行中的标记为已终止。继续?',
      '终止确认',
      { type: 'warning', confirmButtonText: '终止', cancelButtonText: '继续等待' }
    )
  } catch {
    return
  }
  cancelling.value = true
  try {
    await axios.post(`/api/diagnose/scripts/runs/${currentRunId.value}/cancel`)
    ElMessage.info('终止信号已发送, 等待剩余节点收尾')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '终止失败')
    cancelling.value = false
  }
}

// ─── 一键体检 (批量执行 + 汇总报告) ───
const batchDialog = ref({ visible: false, tab: 'business' })
const batchForm = ref({
  target_mode: 'ips',
  node_ids: [],
  manual_ips: '172.16.3.100',
  ssh_user: 'root',
  ssh_password: '',
  ssh_port: 22,
  category: '',
  alert_time: null,
  range_before_min: 5,
  range_after_min: 10,
})
const batchRunning = ref(false)
const batchCancelling = ref(false)
const batchRunId = ref('')
const batchResults = ref([])
const batchProgress = ref({ total: 0 })
const batchCredsLoaded = ref(false)

// 当前体检 tab 下、(可选)指定分类内的启用脚本
const batchCategories = computed(() =>
  batchDialog.value.tab === 'business' ? businessCategories.value : hardwareCategories.value
)
const batchScriptCount = computed(() => scripts.value.filter(s =>
  s.script_tab === batchDialog.value.tab && s.enabled &&
  (!batchForm.value.category || s.category === batchForm.value.category)
).length)
const batchTargetCount = computed(() =>
  batchForm.value.target_mode === 'nodes'
    ? batchForm.value.node_ids.length
    : batchForm.value.manual_ips.split(',').map(s => s.trim()).filter(Boolean).length
)

const VERDICT_ORDER = { fail: 0, error: 1, pass: 2 }
const sortedBatchResults = computed(() =>
  [...batchResults.value].sort((a, b) =>
    (VERDICT_ORDER[a.verdict] ?? 9) - (VERDICT_ORDER[b.verdict] ?? 9) ||
    (a.category || '').localeCompare(b.category || '') ||
    (a.script_name || '').localeCompare(b.script_name || '')
  )
)
const batchCounts = computed(() => {
  const c = { pass: 0, fail: 0, error: 0 }
  for (const r of batchResults.value) c[r.verdict] = (c[r.verdict] || 0) + 1
  return c
})
const batchHealthScore = computed(() => {
  const n = batchResults.value.length
  return n ? Math.round((batchCounts.value.pass / n) * 100) : 0
})
const batchHealthLevel = computed(() => {
  const s = batchHealthScore.value
  return s >= 90 ? 'good' : s >= 60 ? 'warn' : 'bad'
})
function batchRowClass({ row }) {
  return row.verdict === 'fail' ? 'row-fail' : row.verdict === 'error' ? 'row-error' : ''
}

async function openBatchDialog(tab) {
  batchDialog.value = { visible: true, tab }
  batchForm.value.category = ''
  batchResults.value = []
  batchProgress.value = { total: 0 }
  batchRunId.value = ''
  // 预填已保存凭据
  try {
    const res = await axios.get('/api/diagnose/ssh-creds')
    if (res.data.has_saved) {
      batchForm.value.ssh_user = res.data.ssh_user || 'root'
      batchForm.value.ssh_port = res.data.ssh_port || 22
      batchForm.value.ssh_password = PWD_MASK
      batchCredsLoaded.value = true
    } else {
      batchCredsLoaded.value = false
    }
  } catch { batchCredsLoaded.value = false }
  loadNodes()
}

function onBatchDialogClosed() {
  batchResults.value = []
  batchRunId.value = ''
  batchRunning.value = false
  batchCancelling.value = false
}

async function executeBatch() {
  const payload = {
    node_ids: batchForm.value.target_mode === 'nodes' ? batchForm.value.node_ids : [],
    target_ips: batchForm.value.target_mode === 'ips'
      ? batchForm.value.manual_ips.split(',').map(s => s.trim()).filter(Boolean)
      : [],
    ssh_user: batchForm.value.ssh_user,
    ssh_password: batchForm.value.ssh_password,
    ssh_port: Number(batchForm.value.ssh_port) || 22,
    script_tab: batchDialog.value.tab,
    category: batchForm.value.category || null,
    alert_time: batchForm.value.alert_time || null,
    range_before_min: Number(batchForm.value.range_before_min) || 0,
    range_after_min: Number(batchForm.value.range_after_min) || 0,
  }
  batchRunning.value = true
  batchCancelling.value = false
  batchRunId.value = ''
  batchResults.value = []
  batchProgress.value = { total: 0 }

  try {
    const resp = await fetch('/api/diagnose/scripts/batch-run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`
      try { detail = (await resp.json()).detail || detail } catch {}
      throw new Error(detail)
    }
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let endEvent = null
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buf.indexOf('\n\n')) !== -1) {
        const chunk = buf.slice(0, idx).trim()
        buf = buf.slice(idx + 2)
        if (!chunk.startsWith('data:')) continue
        const json = chunk.replace(/^data:\s*/, '')
        if (!json) continue
        let evt
        try { evt = JSON.parse(json) } catch { continue }
        if (evt.type === 'start') {
          batchProgress.value = { total: evt.total }
          batchRunId.value = evt.run_id || ''
        } else if (evt.type === 'result') {
          batchResults.value.push(evt)
        } else if (evt.type === 'end') {
          endEvent = evt
        }
      }
    }
    const total = endEvent?.total ?? batchResults.value.length
    const failed = endEvent?.failed ?? batchCounts.value.fail
    const errored = endEvent?.errored ?? batchCounts.value.error
    const summary = `正常 ${batchCounts.value.pass} · 异常 ${failed} · 错误 ${errored} (共 ${total})`
    if (endEvent?.cancelled) {
      ElMessage.warning(`体检已终止: ${summary}`)
    } else {
      ElMessage[(failed === 0 && errored === 0) ? 'success' : 'warning'](`体检完成: ${summary}`)
    }
    if (batchForm.value.ssh_password && batchForm.value.ssh_password !== PWD_MASK) {
      batchForm.value.ssh_password = PWD_MASK
      batchCredsLoaded.value = true
    }
  } catch (e) {
    ElMessage.error(e.message || '体检失败')
  } finally {
    batchRunning.value = false
    batchCancelling.value = false
    batchRunId.value = ''
  }
}

async function terminateBatch() {
  if (!batchRunId.value || batchCancelling.value) return
  batchCancelling.value = true
  try {
    await axios.post(`/api/diagnose/scripts/runs/${batchRunId.value}/cancel`)
    ElMessage.info('终止信号已发送')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '终止失败')
    batchCancelling.value = false
  }
}

// ─── 日志导出 (SSH 拉取 stdout 落盘) ───
const exportForm = ref({
  target_host: '172.16.3.100',
  ssh_port: 22,
  ssh_user: 'root',
  ssh_password: '',
  output_dir: 'D:\\logs\\export',
  script_ids: [],
  alert_time: null,
  range_before_min: 5,
  range_after_min: 10,
})
const exporting = ref(false)
const cancellingExport = ref(false)
const exportRunId = ref('')
const exportProgress = ref({ total: 0, output_dir: '' })
const exportResults = ref([])
const pickingFolder = ref(false)

// 选输出目录: 优先走 pywebview 桌面原生桥, 浏览器/dev 模式回落到后端 tkinter subprocess
async function pickOutputDir() {
  pickingFolder.value = true
  try {
    const native = window.pywebview?.api?.pick_folder
    if (typeof native === 'function') {
      try {
        const p = await native(exportForm.value.output_dir || '')
        if (p) exportForm.value.output_dir = p
        return
      } catch (e) {
        console.warn('[pickOutputDir] pywebview 桥失败, 回落后端', e)
      }
    }
    const res = await axios.post('/api/diagnose/pick-folder', {
      initial: exportForm.value.output_dir || '',
    })
    if (res.data?.path) {
      exportForm.value.output_dir = res.data.path
    } else {
      ElMessage.info('未选择目录')
    }
  } catch (e) {
    ElMessage.error('选择目录失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    pickingFolder.value = false
  }
}

function toggleScript(id, checked) {
  const arr = exportForm.value.script_ids
  if (checked) {
    if (!arr.includes(id)) arr.push(id)
  } else {
    const i = arr.indexOf(id); if (i >= 0) arr.splice(i, 1)
  }
}
function isCatAllChecked(cat) {
  const ids = getScripts('log_export', cat).map(s => s.id)
  return ids.length > 0 && ids.every(id => exportForm.value.script_ids.includes(id))
}
function isCatIndeterminate(cat) {
  const ids = getScripts('log_export', cat).map(s => s.id)
  const picked = ids.filter(id => exportForm.value.script_ids.includes(id))
  return picked.length > 0 && picked.length < ids.length
}
function toggleCatAll(cat, checked) {
  const ids = getScripts('log_export', cat).map(s => s.id)
  const set = new Set(exportForm.value.script_ids)
  if (checked) ids.forEach(id => set.add(id))
  else         ids.forEach(id => set.delete(id))
  exportForm.value.script_ids = [...set]
}

async function startExport() {
  // 默认凭据补全 (跟脚本运行对话框共用同一份持久化凭据)
  if (!exportForm.value.ssh_password) {
    try {
      const cr = await axios.get('/api/diagnose/ssh-creds')
      if (cr.data?.has_saved) {
        exportForm.value.ssh_password = PWD_MASK
      }
    } catch {}
  }
  exporting.value = true
  cancellingExport.value = false
  exportRunId.value = ''
  exportResults.value = []
  exportProgress.value = { total: 0, output_dir: '' }

  const payload = {
    target_host: exportForm.value.target_host.trim(),
    ssh_port:    Number(exportForm.value.ssh_port) || 22,
    ssh_user:    exportForm.value.ssh_user,
    ssh_password: exportForm.value.ssh_password,
    script_ids:  exportForm.value.script_ids,
    output_dir:  exportForm.value.output_dir,
    alert_time:  exportForm.value.alert_time || null,
    range_before_min: Number(exportForm.value.range_before_min) || 0,
    range_after_min:  Number(exportForm.value.range_after_min)  || 0,
  }

  try {
    const resp = await fetch('/api/diagnose/log-export/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!resp.ok) {
      let detail = `HTTP ${resp.status}`
      try { detail = (await resp.json()).detail || detail } catch {}
      throw new Error(detail)
    }

    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buf = ''
    let endEvent = null
    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true })
      let idx
      while ((idx = buf.indexOf('\n\n')) !== -1) {
        const chunk = buf.slice(0, idx).trim()
        buf = buf.slice(idx + 2)
        if (!chunk.startsWith('data:')) continue
        const json = chunk.replace(/^data:\s*/, '')
        if (!json) continue
        let evt
        try { evt = JSON.parse(json) } catch { continue }

        if (evt.type === 'start') {
          exportProgress.value = { total: evt.total, output_dir: evt.output_dir }
          exportRunId.value = evt.run_id || ''
        } else if (evt.type === 'result') {
          exportResults.value.push(evt)
        } else if (evt.type === 'end') {
          endEvent = evt
        }
      }
    }
    const ok = exportResults.value.filter(r => r.success).length
    const total = exportProgress.value.total || exportResults.value.length
    if (endEvent?.cancelled) {
      ElMessage.warning(`已终止: ${ok}/${total} 个脚本完成, 文件落在 ${endEvent.output_dir}`)
    } else {
      ElMessage[ok === total ? 'success' : 'warning'](
        `导出完成: ${ok}/${total} 成功, 文件落在 ${endEvent?.output_dir || exportProgress.value.output_dir}`
      )
    }
  } catch (e) {
    ElMessage.error(e.message || '导出失败')
  } finally {
    exporting.value = false
    cancellingExport.value = false
    exportRunId.value = ''
  }
}

async function terminateExport() {
  if (!exportRunId.value || cancellingExport.value) return
  cancellingExport.value = true
  try {
    await axios.post(`/api/diagnose/scripts/runs/${exportRunId.value}/cancel`)
    ElMessage.info('终止信号已发送')
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '终止失败')
    cancellingExport.value = false
  }
}

// ─── Helpers ───
const formatDate = d => d ? new Date(d).toLocaleString() : ''

// ─── 发布包管理 ───
const importFileRef = ref(null)
const savingBundle = ref(false)
const bundleInfo = ref({ exists: false, count: 0, mtime: null })

async function loadBundleInfo() {
  try {
    const res = await axios.get('/api/diagnose/scripts/bundle-info')
    bundleInfo.value = res.data
  } catch { /* ignore */ }
}

function exportScripts() {
  window.open('/api/diagnose/scripts/export', '_blank')
}

async function onImportFile(event) {
  const file = event.target.files[0]
  if (!file) return
  event.target.value = ''
  let data
  try {
    data = JSON.parse(await file.text())
  } catch {
    ElMessage.error('文件格式错误，请选择合法的 JSON 文件')
    return
  }
  const scripts = data.scripts || (Array.isArray(data) ? data : null)
  if (!scripts) { ElMessage.error('JSON 中未找到 scripts 字段'); return }

  try {
    await ElMessageBox.confirm(
      `将导入 ${scripts.length} 个脚本（同名脚本将被覆盖），继续？`,
      '导入确认', { type: 'warning', confirmButtonText: '导入', cancelButtonText: '取消' }
    )
    const res = await axios.post('/api/diagnose/scripts/import', { scripts, mode: 'merge' })
    ElMessage.success(`导入完成：新建 ${res.data.created}，更新 ${res.data.updated}`)
    loadScripts()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.detail || '导入失败')
  }
}

// ─── .sh 文件夹包 导入/导出 ───
const dirBusy = ref(false)
const LAST_DIR_KEY = 'diag_scripts_dir'

// 通用目录选择: 优先 pywebview 桌面桥, 回落后端 tkinter subprocess
async function pickFolder(initial) {
  const native = window.pywebview?.api?.pick_folder
  if (typeof native === 'function') {
    try {
      const p = await native(initial || '')
      if (p) return p
    } catch (e) { console.warn('[pickFolder] pywebview 桥失败, 回落后端', e) }
  }
  try {
    const res = await axios.post('/api/diagnose/pick-folder', { initial: initial || '' })
    return res.data?.path || ''
  } catch (e) {
    ElMessage.error('选择目录失败: ' + (e.response?.data?.detail || e.message))
    return ''
  }
}

async function exportToDir() {
  const dir = await pickFolder(localStorage.getItem(LAST_DIR_KEY) || '')
  if (!dir) return
  localStorage.setItem(LAST_DIR_KEY, dir)
  dirBusy.value = true
  try {
    const res = await axios.post('/api/diagnose/scripts/export-dir', { dir })
    ElMessage.success(`已导出 ${res.data.count} 个脚本到 ${res.data.dir}`)
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '导出失败')
  } finally {
    dirBusy.value = false
  }
}

async function importFromDir() {
  const dir = await pickFolder(localStorage.getItem(LAST_DIR_KEY) || '')
  if (!dir) return
  localStorage.setItem(LAST_DIR_KEY, dir)
  try {
    await ElMessageBox.confirm(
      `将扫描「${dir}」下所有 .sh 脚本，按 tab/分类/名称合并导入（同名覆盖）。继续？`,
      '从目录导入', { type: 'warning', confirmButtonText: '导入', cancelButtonText: '取消' }
    )
  } catch { return }
  dirBusy.value = true
  try {
    const res = await axios.post('/api/diagnose/scripts/import-dir', { dir, mode: 'merge' })
    ElMessage.success(`导入完成：新建 ${res.data.created}，更新 ${res.data.updated}`)
    loadScripts()
  } catch (e) {
    ElMessage.error(e.response?.data?.detail || '导入失败')
  } finally {
    dirBusy.value = false
  }
}

async function saveBundle() {
  try {
    await ElMessageBox.confirm(
      '将当前数据库中的全部脚本保存为发布配置（scripts_bundle.json）。\n新环境首次启动时将自动加载此配置。',
      '保存为发布配置', { type: 'info', confirmButtonText: '保存', cancelButtonText: '取消' }
    )
    savingBundle.value = true
    const res = await axios.post('/api/diagnose/scripts/save-bundle')
    ElMessage.success(res.data.message)
    loadBundleInfo()
  } catch (e) {
    if (e !== 'cancel') ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    savingBundle.value = false
  }
}

// ─── Init ───
async function loadScripts() {
  try {
    const res = await axios.get('/api/diagnose/scripts')
    scripts.value = res.data
  } catch { ElMessage.error('加载脚本失败') }
}

async function loadNodes() {
  try {
    const res = await axios.get('/api/nodes')
    nodes.value = res.data
  } catch { /* ignore */ }
}

// 打开运行对话框前刷新一次节点状态, 避免列表里出现已离线的旧节点

onMounted(() => {
  loadScripts()
  loadNodes()
  loadBundleInfo()
})
</script>

<style scoped>
/* ─── 整体 ─── */
.diagnose-view {
  height: 100%;
  display: flex;
  flex-direction: column;
}

/* ─── 发布配置操作栏 ─── */
.scripts-mgmt-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  background: #0d1b2e;
  border-bottom: 1px solid #0f3460;
  flex-shrink: 0;
}
.bar-label {
  font-size: 12px;
  font-weight: 600;
  color: #5577aa;
  letter-spacing: 0.5px;
  text-transform: uppercase;
}
.bar-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.bundle-tag {
  font-size: 11px;
}

/* ─── Tabs 深色风格 ─── */
.diag-tabs { flex: 1; }

.diag-tabs :deep(.el-tabs__header) {
  background: #16213e;
  border-bottom: 2px solid #0f3460;
  margin-bottom: 0;
  padding: 0 4px;
}
.diag-tabs :deep(.el-tabs__nav-wrap::after) {
  background-color: transparent;
}
.diag-tabs :deep(.el-tabs__item) {
  color: #8899aa;
  height: 46px;
  line-height: 46px;
  padding: 0 26px;
  font-size: 14px;
  letter-spacing: 0.3px;
}
.diag-tabs :deep(.el-tabs__item:hover) { color: #e94560; }
.diag-tabs :deep(.el-tabs__item.is-active) {
  color: #e94560;
  font-weight: 600;
}
.diag-tabs :deep(.el-tabs__active-bar) { background-color: #e94560; }
.diag-tabs :deep(.el-tabs__content) {
  padding: 20px;
  background: transparent;
  overflow-y: auto;
}

/* ─── Toolbar ─── */
.tab-toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 22px;
}

/* ─── 分类区块 ─── */
.empty-hint {
  color: #666;
  padding: 40px;
  text-align: center;
}
.category-section { margin-bottom: 30px; }
.category-header {
  display: flex;
  align-items: center;
  gap: 8px;
  color: #fff;
  font-size: 14px;
  font-weight: 600;
  margin-bottom: 14px;
  padding-bottom: 8px;
  border-bottom: 2px solid #e94560;
}
.cat-bullet { color: #e94560; font-size: 15px; }

/* ─── 脚本卡片 ─── */
.script-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.script-card {
  background: #0f3460;
  border: 1px solid rgba(233, 69, 96, 0.2);
  border-radius: 8px;
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.script-card:hover {
  border-color: #e94560;
  box-shadow: 0 4px 14px rgba(233, 69, 96, 0.18);
}
.script-card--disabled { opacity: 0.5; }
.script-card--selected {
  border-color: #67c23a;
  box-shadow: 0 0 0 1px rgba(103, 194, 58, 0.35) inset;
}

.script-card-body { flex: 1; }
.sc-name { font-weight: 600; font-size: 14px; color: #fff; margin-bottom: 4px; }
.sc-desc { font-size: 12px; color: #8899aa; min-height: 34px; line-height: 1.6; }
.sc-meta { display: flex; align-items: center; gap: 8px; margin-top: 8px; }
.sc-timeout { font-size: 11px; color: #556; }

.script-card-footer { display: flex; gap: 6px; }

.script-card-empty {
  border: 1px dashed rgba(233, 69, 96, 0.3);
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 110px;
  color: #556;
}

/* ─── 日志采集 ─── */
.query-card { margin-bottom: 16px; }
.form-section-label {
  color: #a0a0a0;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.8px;
  text-transform: uppercase;
  margin-bottom: 10px;
}
.vert-checks { display: flex; flex-direction: column; gap: 10px; }
.vert-checks :deep(.el-checkbox__label) { color: #d0d0d0; }

.card-header { display: flex; justify-content: space-between; align-items: center; }

/* ─── 脚本编辑 ─── */
.code-textarea :deep(textarea) {
  font-family: 'Consolas', 'Monaco', monospace !important;
  font-size: 13px;
  background: #0d1117;
  color: #c9d1d9;
  border-color: #30363d;
}
.import-hint { margin-top: 6px; }

/* ─── 运行对话框 ─── */
.run-form { flex-wrap: wrap; gap: 4px; }
.run-form-block { width: 100%; }
.run-form-block :deep(.el-form-item) { margin-bottom: 12px; }
.run-ip-hint {
  font-size: 11px;
  color: #8b949e;
  margin-top: 4px;
}
.run-form-block :deep(.el-radio-button__inner) {
  background: #0f3460;
  border-color: #1e4080;
  color: #8b949e;
}
.run-form-block :deep(.el-radio-button__original-radio:checked + .el-radio-button__inner) {
  background: #e94560;
  border-color: #e94560;
  color: #fff;
}

.run-action-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 14px;
}
.run-progress {
  color: #8b949e;
  font-size: 12px;
}
.run-id-tag {
  color: #5a7090;
  font-size: 11px;
  font-family: Consolas, monospace;
  margin-left: 4px;
}
.range-label {
  color: #a0a0a0;
  font-size: 13px;
  margin: 0 8px;
}
.range-label:first-child { margin-left: 0; }
.run-form-block code {
  color: #79c0ff;
  background: #0d1117;
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 11px;
}
.run-host {
  color: #8b949e;
  font-size: 11px;
  font-family: Consolas, monospace;
  margin-left: 8px;
}
.run-empty-hint {
  color: #e0a64b;
  font-size: 11px;
  margin-left: 8px;
}
.script-preview {
  background: #0d1117;
  color: #8b949e;
  border: 1px solid #30363d;
  border-radius: 6px;
  padding: 12px 14px;
  font-family: 'Consolas', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  max-height: 120px;
  overflow: auto;
  margin-bottom: 14px;
}
.run-result {
  margin-bottom: 14px;
  border: 1px solid #0f3460;
  border-radius: 6px;
  overflow: hidden;
}
.run-result-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  background: #0f3460;
  color: #fff;
  font-weight: 500;
}
.run-verdict-tags { display: flex; gap: 6px; align-items: center; }

/* ─── 一键体检报告 ─── */
.report-stats {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 8px 0 14px;
  flex-wrap: wrap;
}
.stat-chip {
  font-size: 13px;
  color: #c9d1d9;
  background: #0f3460;
  border-radius: 6px;
  padding: 5px 12px;
}
.stat-chip b { font-size: 15px; margin-left: 4px; }
.stat-pass b { color: #67c23a; }
.stat-fail b { color: #f56c6c; }
.stat-error b { color: #909399; }
.report-health {
  margin-left: auto;
  font-size: 13px;
  font-weight: 700;
  padding: 5px 14px;
  border-radius: 6px;
}
.report-health.health-good { color: #67c23a; background: rgba(103,194,58,0.12); }
.report-health.health-warn { color: #e6a23c; background: rgba(230,162,60,0.12); }
.report-health.health-bad  { color: #f56c6c; background: rgba(245,108,108,0.14); }
.report-expand { padding: 6px 12px; }
.report-sug { color: #e0a64b; }
.report-err { color: #ff7b7b; }
.report-ok  { color: #67c23a; }
:deep(.row-fail) { --el-table-tr-bg-color: rgba(245,108,108,0.08); }
:deep(.row-error) { --el-table-tr-bg-color: rgba(144,147,153,0.08); }
.run-suggestion {
  display: flex;
  align-items: center;
  background: #2b1d0a;
  color: #e0a64b;
  font-size: 12px;
  padding: 8px 14px;
  border-bottom: 1px solid #3a2a10;
}
.run-stdout {
  background: #0d1117;
  color: #c9d1d9;
  font-family: 'Consolas', monospace;
  font-size: 12px;
  margin: 0;
  padding: 10px 14px;
  white-space: pre-wrap;
  max-height: 300px;
  overflow: auto;
}
.run-stderr {
  background: #1c0a0a;
  color: #ff7b7b;
  font-family: 'Consolas', monospace;
  font-size: 12px;
  margin: 0;
  padding: 8px 14px;
  white-space: pre-wrap;
  max-height: 140px;
  overflow: auto;
}
</style>

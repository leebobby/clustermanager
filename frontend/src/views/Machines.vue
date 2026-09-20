<template>
  <div class="machines">
    <el-tabs v-model="tab">
      <!-- ── 节点 ────────────────────────────────────────────────── -->
      <el-tab-pane label="节点" name="nodes">
        <div class="pane">
          <header class="bar cm-card">
            <span class="bar-title">{{ ws.machineType || '未选机台类型' }}</span>
            <span class="bar-sub">
              {{ nodes.length }} 台 · 由模板加载。改完模板点「重新加载」对齐, 实测状态会保留
            </span>
            <div class="spacer"></div>
            <el-button size="small" type="primary" plain :disabled="!ready" @click="openNode()">加节点</el-button>
            <el-button size="small" :disabled="!ready || !nodes.length" @click="exportNodes">导出 nodes.json</el-button>
            <el-button size="small" :loading="reloading" :disabled="!ready" @click="reload">重新加载</el-button>
            <!-- 正路是改模板再「重新加载」; 这个入口只管现场 IP 和模板算出来的对不上
                 那种情况(比如前段第二个口手配成了别的), 所以做成不显眼的一行小字 -->
            <el-button link size="small" :disabled="!ready" class="rescue" @click="openImport">
              从 nodes.json 反填
            </el-button>
          </header>

          <el-alert
            v-if="noIpNodes.length" type="warning" show-icon :closable="false"
            :title="`${noIpNodes.length} 台节点一个 IP 都没有`"
          >
            <div class="issue">
              IP 是按模板里角色的平面网段生成的。这些节点的角色在模板里没配平面或没填网段:
              {{ noIpRoles.join('、') }} —— 到「模板」页补上, 再回来点「重新加载」。
            </div>
          </el-alert>

          <el-table :data="nodes" class="cm-card" empty-text="还没有节点" max-height="620">
            <el-table-column prop="hostname" label="主机名" min-width="130">
              <template #default="{ row }"><span class="cm-mono bold">{{ row.hostname }}</span></template>
            </el-table-column>
            <el-table-column prop="role_key" label="角色" width="110" />
            <el-table-column label="整机" width="88">
              <template #default="{ row }">
                <span class="cm-chip" :class="`cm-chip--${statusClass(row.status)}`">
                  {{ STATUS_TEXT[row.status] || '未检测' }}
                </span>
              </template>
            </el-table-column>
            <el-table-column
              v-for="p in PLANE_KEYS"
              :key="p"
              :label="PLANE_LABEL[p]"
              min-width="150"
            >
              <template #default="{ row }">
                <div v-if="(row.plane_ips || {})[p]" class="ip-cell">
                  <span
                    v-for="ip in row.plane_ips[p]"
                    :key="ip"
                    class="cm-mono ip"
                    :style="{ color: PLANE_COLOR[p] }"
                  >{{ ip }}</span>
                  <span class="cm-chip cm-chip--tiny" :class="`cm-chip--${statusClass((row.plane_status || {})[p])}`">
                    {{ STATUS_TEXT[(row.plane_status || {})[p]] || '未检测' }}
                  </span>
                </div>
                <span v-else class="muted">—</span>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="110" align="right" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" size="small" @click="openNode(row)">编辑</el-button>
                <el-button link type="danger" size="small" @click="removeNode(row)">删除</el-button>
              </template>
            </el-table-column>
          </el-table>
        </div>
      </el-tab-pane>

      <!-- ── 模板 ────────────────────────────────────────────────── -->
      <el-tab-pane label="模板" name="templates">
        <div class="pane">
          <header class="bar cm-card">
            <span class="bar-title">产品与机台类型</span>
            <span class="bar-sub">产品定义角色, 机台类型只定各角色几台。存 JSON 文件, 不入库。</span>
            <div class="spacer"></div>
            <el-button @click="openTplImport">导入模板</el-button>
            <el-dropdown trigger="click" :disabled="!saved.length" @command="exportTemplates">
              <el-button :disabled="!saved.length">
                导出模板<el-icon class="el-icon--right"><arrow-down /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="">整份 ({{ saved.length }} 个产品)</el-dropdown-item>
                  <el-dropdown-item
                    v-for="p in saved" :key="p.name" :command="p.name" divided
                  >只导「{{ p.name }}」</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>
            <el-button @click="addProduct">新增产品</el-button>
            <el-button type="primary" :loading="saving" @click="saveTemplates">保存模板</el-button>
          </header>

          <el-alert v-if="tplError" :title="tplError" type="error" show-icon :closable="false" />
          <el-alert
            v-if="tplProblems.length" type="error" show-icon :closable="false"
            title="模板里有画不出图的地方, 保存前要先改掉"
          >
            <div v-for="m in tplProblems" :key="m" class="issue">{{ m }}</div>
          </el-alert>
          <el-alert
            v-if="tplWarnings.length" type="warning" show-icon :closable="false" title="提醒"
          >
            <div v-for="m in tplWarnings" :key="m" class="issue">{{ m }}</div>
          </el-alert>

          <el-tabs v-if="draft.length" v-model="activeProduct" type="border-card" class="cm-card">
            <el-tab-pane
              v-for="(p, pi) in draft"
              :key="pi"
              :name="String(pi)"
              :label="p.name || '(未命名)'"
            >
              <div class="prod">
                <div class="row">
                  <el-input v-model="p.name" placeholder="产品名称, 如 A" style="width: 240px" />
                  <el-input v-model="p.description" placeholder="说明" />
                  <el-button type="danger" plain @click="draft.splice(pi, 1)">删除产品</el-button>
                </div>

                <div class="sub">
                  <span class="sub-title">角色</span>
                  <span class="sub-hint">key 是角色标识, 定下就别改 —— 机台类型的台数按它索引。主机名前缀可以随便改。</span>
                  <div class="spacer"></div>
                  <el-button size="small" @click="addRole(p)">加角色</el-button>
                </div>

                <el-table
                  :data="p.roles" size="small" border
                  row-key="_uid"
                  :expand-row-keys="expanded"
                  @expand-change="onExpand"
                >
                  <el-table-column type="expand">
                    <template #default="{ row }">
                      <div class="expand">
                        <div class="exp-block">
                          <span class="exp-title">接哪几个平面</span>
                          <span class="exp-hint">
                            组网图和诊断项都从这里推出来。同一个平面可以加多块网卡 ——
                            Master 数据面就是前段 DPDK 两块 + 后段 RDMA 两块, 一共四个 IP,
                            诊断时四个口各查一次。
                          </span>
                          <div v-for="plane in meta.planes" :key="plane.key" class="plane-block">
                            <div class="plane-head">
                              <el-checkbox
                                :model-value="hasPlane(row, plane.key)"
                                @change="togglePlane(row, plane.key, $event)"
                              >
                                <span :style="{ color: PLANE_COLOR[plane.key], fontWeight: 700 }">{{ plane.label }}</span>
                              </el-checkbox>
                              <template v-if="hasPlane(row, plane.key)">
                                <el-input
                                  v-if="plane.key.startsWith('data')"
                                  :model-value="planeOf(row, plane.key).protocol"
                                  placeholder="协议 DPDK / RDMA"
                                  size="small" style="width: 160px"
                                  @update:model-value="v => (planeOf(row, plane.key).protocol = v)"
                                />
                                <el-button size="small" link type="primary"
                                  @click="planeOf(row, plane.key).prefixes.push('')">加网卡</el-button>
                              </template>
                            </div>
                            <div v-if="hasPlane(row, plane.key)" class="nics">
                              <div
                                v-for="(pref, ni) in planeOf(row, plane.key).prefixes"
                                :key="ni"
                                class="nic"
                              >
                                <span class="nic-no">第 {{ ni + 1 }} 口</span>
                                <el-input
                                  :model-value="pref"
                                  placeholder="网段前缀 如 200.1.1."
                                  size="small" style="width: 200px"
                                  @update:model-value="v => (planeOf(row, plane.key).prefixes[ni] = v)"
                                />
                                <span class="nic-eg cm-mono">
                                  {{ pref ? `${String(pref).replace(/\.$/, '')}.${row.ip_start}` : '—' }}
                                </span>
                                <el-button
                                  link type="danger" size="small"
                                  @click="planeOf(row, plane.key).prefixes.splice(ni, 1)"
                                >删</el-button>
                              </div>
                              <span v-if="!planeOf(row, plane.key).prefixes.length" class="muted">
                                还没加网卡, 这个平面不会生成 IP
                              </span>
                            </div>
                          </div>
                        </div>

                        <div class="exp-block">
                          <span class="exp-title">角色专项检查</span>
                          <span class="exp-hint">
                            打钩的会进一键诊断的可选项。ping / BMC / SSH 由后端直接探; 其余要由
                            诊断脚本认领, 没脚本认领的会标成"缺脚本", 勾了也跑不出结果。
                          </span>
                          <el-checkbox-group v-model="row.checks">
                            <el-checkbox v-for="c in meta.checks" :key="c.key" :value="c.key">
                              {{ c.label }}
                              <span class="muted">({{ c.kind === 'builtin' ? '内建' : '需脚本' }})</span>
                            </el-checkbox>
                          </el-checkbox-group>
                        </div>

                        <div class="exp-block">
                          <span class="exp-title">硬件规格与备注</span>
                          <div class="row">
                            <el-input v-model="row.os_version" placeholder="系统版本" style="width: 220px" />
                            <el-input-number v-model="row.cpu_cores" :min="0" placeholder="核" controls-position="right" style="width: 120px" />
                            <el-input-number v-model="row.memory_gb" :min="0" placeholder="内存 GB" controls-position="right" style="width: 130px" />
                            <el-input-number v-model="row.disk_gb" :min="0" placeholder="磁盘 GB" controls-position="right" style="width: 140px" />
                          </div>
                          <el-input v-model="row.note" placeholder="备注, 会显示在组网图的角色框里" />
                        </div>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="key" width="126">
                    <template #default="{ row }">
                      <el-input v-model="row.key" size="small" placeholder="master"
                        @blur="normalizeKey(p, row)" />
                    </template>
                  </el-table-column>
                  <el-table-column label="显示名" width="136">
                    <template #default="{ row }"><el-input v-model="row.label" size="small" placeholder="Master" /></template>
                  </el-table-column>
                  <el-table-column label="节点类型" width="116">
                    <template #default="{ row }"><el-input v-model="row.node_type" size="small" /></template>
                  </el-table-column>
                  <el-table-column label="主机名前缀" width="126">
                    <template #default="{ row }"><el-input v-model="row.hostname_prefix" size="small" /></template>
                  </el-table-column>
                  <el-table-column label="名序号起" width="96">
                    <template #default="{ row }"><el-input-number v-model="row.hostname_start" :min="0" size="small" controls-position="right" style="width: 80px" /></template>
                  </el-table-column>
                  <el-table-column label="IP 起" width="96">
                    <template #default="{ row }"><el-input-number v-model="row.ip_start" :min="0" size="small" controls-position="right" style="width: 80px" /></template>
                  </el-table-column>
                  <el-table-column label="平面 / 网卡数" min-width="180">
                    <template #default="{ row }">
                      <span v-for="pl in row.planes" :key="pl.plane" class="plane-tag"
                        :style="{ color: PLANE_COLOR[pl.plane] }">
                        {{ SHORT_PLANE[pl.plane] }}<template v-if="pl.prefixes.length > 1">&times;{{ pl.prefixes.length }}</template>
                        <span v-if="!pl.prefixes.some(x => x)" class="tag-bad">无网段</span>
                      </span>
                      <!-- 没配平面 = 节点不会有 IP、组网图画不出来。这是最容易漏的一格, 要喊出来 -->
                      <a v-if="!row.planes.length" class="tag-bad-link" @click="expandRole(row)">
                        未配平面 → 不会生成 IP, 点这里配
                      </a>
                    </template>
                  </el-table-column>
                  <el-table-column width="56" align="right">
                    <template #default="{ $index }">
                      <el-button link type="danger" size="small" @click="p.roles.splice($index, 1)">删</el-button>
                    </template>
                  </el-table-column>
                </el-table>

                <div class="sub">
                  <span class="sub-title">机台类型</span>
                  <span class="sub-hint">同一产品下的区别只有台数。比如 A11 和 A12。</span>
                  <div class="spacer"></div>
                  <el-button size="small" @click="addMachine(p)">加机台类型</el-button>
                </div>

                <el-table :data="p.machine_types" size="small" border>
                  <el-table-column label="名称" width="170">
                    <template #default="{ row }"><el-input v-model="row.name" size="small" placeholder="A11" /></template>
                  </el-table-column>
                  <el-table-column label="说明" min-width="160">
                    <template #default="{ row }"><el-input v-model="row.description" size="small" /></template>
                  </el-table-column>
                  <el-table-column
                    v-for="role in p.roles"
                    :key="role.key"
                    :label="role.label || role.key"
                    width="108"
                  >
                    <template #default="{ row }">
                      <el-input-number
                        :model-value="row.counts[role.key] || 0"
                        :min="0" size="small" controls-position="right" style="width: 90px"
                        @update:model-value="v => (row.counts[role.key] = v || 0)"
                      />
                    </template>
                  </el-table-column>
                  <el-table-column label="合计" width="78">
                    <template #default="{ row }">{{ total(row) }} 台</template>
                  </el-table-column>
                  <el-table-column width="56" align="right">
                    <template #default="{ $index }">
                      <el-button link type="danger" size="small" @click="p.machine_types.splice($index, 1)">删</el-button>
                    </template>
                  </el-table-column>
                </el-table>
              </div>
            </el-tab-pane>
          </el-tabs>

          <el-empty v-else description="还没有产品, 点右上「新增产品」" />
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- ── 导入模板 ────────────────────────────────────────────── -->
    <el-dialog v-model="tplImpOpen" title="导入模板" width="820px" top="6vh">
      <p class="imp-hint">
        模板是这个工具里唯一要在机器之间搬的东西 —— 产品有哪些角色、每个角色接哪几个平面、
        网段怎么排、机台类型各几台。节点是照着模板生成的, 导进模板再「重新加载」就都对齐了。
        <br />
        认 <code>node_templates.json</code> 原样的格式, 所以导出改几行再导回来是闭环的。
        先给预览, 确认了才写文件。
      </p>

      <div class="imp-pick">
        <input ref="tplFileInput" type="file" accept=".json,application/json" @change="onTplPick" />
        <span v-if="tplImpFile" class="imp-file cm-mono">{{ tplImpFile.name }}</span>
        <el-button v-if="tplImpFile" link type="primary" size="small" :loading="tplImporting"
          @click="tplPreview">重新解析</el-button>
      </div>

      <div class="imp-mode">
        <el-radio-group v-model="tplImpMode" size="small" @change="tplImpFile && tplPreview()">
          <el-radio-button value="merge">合并</el-radio-button>
          <el-radio-button value="replace">整份替换</el-radio-button>
        </el-radio-group>
        <span class="muted">{{ tplImpMode === 'merge'
          ? '同名产品整个换掉, 新产品追加, 文件里没提到的产品留着'
          : '模板文件整份换成这一份 —— 文件里没有的产品会被删掉' }}</span>
      </div>

      <el-alert v-if="tplImpError" :title="tplImpError" type="error" show-icon :closable="false" />

      <template v-if="tplImpPreview">
        <div class="imp-sum">
          <span class="cm-chip cm-chip--brand">新增 {{ tplImpPreview.summary.create }}</span>
          <span class="cm-chip cm-chip--warn">覆盖 {{ tplImpPreview.summary.update }}</span>
          <span class="cm-chip cm-chip--idle">不变 {{ tplImpPreview.summary.unchanged }}</span>
          <span v-if="tplImpPreview.summary.kept" class="cm-chip cm-chip--idle">
            原样留着 {{ tplImpPreview.summary.kept }}
          </span>
          <span v-if="tplImpPreview.summary.dropped" class="cm-chip cm-chip--fail">
            删掉 {{ tplImpPreview.summary.dropped }}
          </span>
        </div>

        <!-- 存下去不会报错, 但节点会没 IP、组网图会是空的 —— 这一类直接挡住 -->
        <el-alert
          v-if="tplImpPreview.errors && tplImpPreview.errors.length"
          type="error" show-icon :closable="false" title="这份模板有画不出图的地方, 先改文件再导"
        >
          <div v-for="m in tplImpPreview.errors" :key="m" class="issue">{{ m }}</div>
        </el-alert>
        <el-alert
          v-if="tplImpPreview.problems && tplImpPreview.problems.length"
          type="warning" show-icon :closable="false" title="这些没认出来, 导进去不会生效"
        >
          <div v-for="m in tplImpPreview.problems" :key="m" class="issue">{{ m }}</div>
        </el-alert>
        <el-alert
          v-if="tplImpPreview.warnings && tplImpPreview.warnings.length"
          type="warning" show-icon :closable="false" title="提醒"
        >
          <div v-for="m in tplImpPreview.warnings" :key="m" class="issue">{{ m }}</div>
        </el-alert>

        <el-table :data="tplImpPreview.items" size="small" max-height="300" border>
          <el-table-column label="动作" width="72">
            <template #default="{ row }">
              <span class="cm-chip cm-chip--tiny" :class="ACTION_CLASS[row.action]">
                {{ TPL_ACTION_TEXT[row.action] }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="产品" min-width="150">
            <template #default="{ row }"><span class="bold">{{ row.name }}</span></template>
          </el-table-column>
          <el-table-column prop="roles" label="角色" width="70" align="right" />
          <el-table-column prop="machine_types" label="机台类型" width="86" align="right" />
          <el-table-column label="具体变化" min-width="300">
            <template #default="{ row }">
              <div v-if="row.notes.length">
                <div v-for="n in row.notes" :key="n" class="issue">{{ n }}</div>
              </div>
              <span v-else class="muted">和现在的一模一样</span>
            </template>
          </el-table-column>
        </el-table>

        <div v-if="tplImpPreview.dropped.length" class="imp-missing">
          <span class="warn-text">整份替换会删掉这些产品:</span>
          <span class="cm-mono">{{ tplImpPreview.dropped.join('、') }}</span>
          <span class="muted">—— 它们下面已经生成的节点也会跟着没</span>
        </div>
        <div v-else-if="tplImpPreview.kept.length" class="imp-missing">
          <span class="muted">文件里没提到、原样留着:</span>
          <span class="cm-mono">{{ tplImpPreview.kept.join('、') }}</span>
        </div>
      </template>

      <template #footer>
        <el-button @click="tplImpOpen = false">取消</el-button>
        <el-button
          type="primary" :loading="tplImporting"
          :disabled="!tplImpPreview || (tplImpPreview.errors || []).length > 0"
          @click="doTplImport"
        >确认导入</el-button>
      </template>
    </el-dialog>

    <!-- ── 导入 nodes.json ──────────────────────────────────────── -->
    <el-dialog v-model="importOpen" title="导入 nodes.json" width="860px" top="6vh">
      <p class="imp-hint">
        模板排出来的是"该长什么样", nodes.json 是现场"实际是什么样"。两边对不上时以文件为准 ——
        比如 Master 前段第二个口, 模板按等差数列算的和现场手配的常常不是一个。
        <br />
        认 PXE 那份按 MAC 索引的格式(<code>hostname_new / ctrl_ip / dpdk_ips / rdma_ips / bmc_ip</code>),
        IP 带不带掩码都行。先给预览, 确认了才写库。
      </p>

      <div class="imp-pick">
        <input ref="fileInput" type="file" accept=".json,application/json" @change="onPick" />
        <span v-if="importFile" class="imp-file cm-mono">{{ importFile.name }}</span>
        <el-button v-if="importFile" link type="primary" size="small" :loading="importing"
          @click="preview">重新解析</el-button>
      </div>

      <el-alert v-if="importError" :title="importError" type="error" show-icon :closable="false" />

      <template v-if="importPreview">
        <div class="imp-sum">
          <span class="cm-chip cm-chip--brand">新增 {{ importPreview.summary.create }}</span>
          <span class="cm-chip cm-chip--warn">更新 {{ importPreview.summary.update }}</span>
          <span class="cm-chip cm-chip--idle">不变 {{ importPreview.summary.unchanged }}</span>
          <span v-if="importPreview.summary.missing" class="cm-chip cm-chip--idle">
            模板里有而文件里没有 {{ importPreview.summary.missing }}
          </span>
        </div>

        <el-alert
          v-if="importPreview.problems && importPreview.problems.length"
          type="warning" show-icon :closable="false" title="这些没认出来, 不会导入"
        >
          <div v-for="m in importPreview.problems" :key="m" class="issue">{{ m }}</div>
        </el-alert>

        <el-table :data="importPreview.items" size="small" max-height="360" border>
          <el-table-column label="动作" width="72">
            <template #default="{ row }">
              <span class="cm-chip cm-chip--tiny" :class="ACTION_CLASS[row.action]">
                {{ ACTION_TEXT[row.action] }}
              </span>
            </template>
          </el-table-column>
          <el-table-column label="主机名" width="120">
            <template #default="{ row }"><span class="cm-mono bold">{{ row.hostname }}</span></template>
          </el-table-column>
          <el-table-column prop="role_label" label="角色" width="100" />
          <el-table-column v-for="pk in PLANE_KEYS" :key="pk" :label="SHORT_PLANE[pk]" min-width="140">
            <template #default="{ row }">
              <div v-if="(row.plane_ips || {})[pk]" class="ip-cell">
                <span v-for="ip in row.plane_ips[pk]" :key="ip" class="cm-mono ip"
                  :style="{ color: PLANE_COLOR[pk] }">{{ ip }}</span>
                <span v-if="row.changed_planes.includes(pk)" class="imp-changed">改</span>
              </div>
              <span v-else class="muted">—</span>
            </template>
          </el-table-column>
        </el-table>

        <!-- 逐条的提醒放表格下面: 塞进表格里那一列会被挤到横向滚动之外, 等于没写 -->
        <div v-if="importNotes.length" class="imp-notes">
          <div v-for="n in importNotes" :key="n.key" class="imp-note">
            <span class="cm-mono bold">{{ n.hostname }}</span> {{ n.text }}
          </div>
        </div>

        <div v-if="importPreview.missing.length" class="imp-missing">
          <el-checkbox v-model="removeMissing">
            把文件里没有的那 {{ importPreview.missing.length }} 台模板节点删掉
          </el-checkbox>
          <span class="muted">{{ importPreview.missing.slice(0, 6).join('、') }}{{
            importPreview.missing.length > 6 ? ' …' : '' }}</span>
        </div>
      </template>

      <template #footer>
        <el-button @click="importOpen = false">取消</el-button>
        <el-button type="primary" :disabled="!importPreview" :loading="importing"
          @click="doImport">确认导入</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="nodeOpen" :title="nodeForm.id ? '编辑节点' : '加节点'" width="560px">
      <el-form label-width="96px">
        <el-form-item label="主机名"><el-input v-model="nodeForm.hostname" placeholder="如 slave-13" /></el-form-item>
        <el-form-item label="角色">
          <el-select v-model="nodeForm.role_key" style="width: 100%" @change="onNodeRole">
            <el-option v-for="r in currentRoles" :key="r.key" :label="`${r.label} (${r.key})`" :value="r.key" />
          </el-select>
        </el-form-item>
        <el-form-item label="节点类型"><el-input v-model="nodeForm.node_type" /></el-form-item>

        <!-- 一个平面可以有多块网卡, 每个口一个输入框。Master 数据面是四个 IP:
             前段 DPDK 两个 + 后段 RDMA 两个, 挤在一个框里填不下 -->
        <el-form-item v-for="pl in nodePlanes" :key="pl.plane" :label="pl.label">
          <div class="nic-list">
            <div v-for="(ip, i) in nodeForm.plane_ips[pl.plane]" :key="i" class="nic-line">
              <span class="nic-no">第 {{ i + 1 }} 口</span>
              <el-input
                :model-value="ip" :placeholder="pl.placeholders[i] || 'IP 地址'"
                @update:model-value="v => (nodeForm.plane_ips[pl.plane][i] = v)"
              />
              <el-button link type="danger" size="small"
                @click="nodeForm.plane_ips[pl.plane].splice(i, 1)">删</el-button>
            </div>
            <div class="nic-foot">
              <el-button link type="primary" size="small"
                @click="nodeForm.plane_ips[pl.plane].push('')">加一个口</el-button>
              <span v-if="pl.protocol" class="nic-proto">{{ pl.protocol }}</span>
              <span v-if="pl.plane === 'management'" class="nic-proto">BMC 同网段</span>
              <span v-if="!nodeForm.plane_ips[pl.plane].length" class="muted">没有口, 这个平面不参与诊断</span>
            </div>
          </div>
        </el-form-item>

        <el-form-item label="系统"><el-input v-model="nodeForm.os_version" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="nodeOpen = false">取消</el-button>
        <el-button type="primary" :loading="savingNode" @click="saveNode">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import axios from 'axios'
import { ArrowDown } from '@element-plus/icons-vue'
import { ws, ready, loadWorkspace, reloadNodes } from '@/stores/workspace'
import { planeColors, PLANE_LABEL } from '@/styles/tokens'

const PLANE_COLOR = planeColors()
const PLANE_KEYS = ['management', 'control', 'data_front', 'data_back']
const SHORT_PLANE = { management: '管', control: '控', data_front: '前', data_back: '后' }
const STATUS_TEXT = { online: '通', offline: '断', degraded: '异常', planned: '规划中', unknown: '未检测' }

const tab = ref('nodes')
const nodes = ref([])
const reloading = ref(false)

const saved = ref([])
const draft = ref([])
const meta = ref({ planes: [], checks: [] })
const activeProduct = ref('0')
const saving = ref(false)
const tplError = ref('')
const tplProblems = ref([])
const tplWarnings = ref([])
const expanded = ref([])

const nodeOpen = ref(false)
const savingNode = ref(false)
const nodeForm = ref({})

const importOpen = ref(false)
const importing = ref(false)
const importFile = ref(null)
const importPreview = ref(null)
const importError = ref('')
const removeMissing = ref(false)
const fileInput = ref(null)

const importNotes = computed(() => {
  const out = []
  ;(importPreview.value?.items || []).forEach(it => {
    (it.notes || []).forEach(text => out.push({ key: `${it.hostname}|${text}`, hostname: it.hostname, text }))
  })
  return out
})

const ACTION_TEXT = { create: '新增', update: '更新', unchanged: '不变' }
// 产品是整个换掉的, 说"更新"不够准 —— 覆盖才是实际发生的事
const TPL_ACTION_TEXT = { create: '新增', update: '覆盖', unchanged: '不变' }
const ACTION_CLASS = {
  create: 'cm-chip--brand', update: 'cm-chip--warn', unchanged: 'cm-chip--idle',
}

const tplImpOpen = ref(false)
const tplImporting = ref(false)
const tplImpFile = ref(null)
const tplImpPreview = ref(null)
const tplImpError = ref('')
const tplImpMode = ref('merge')
const tplFileInput = ref(null)

const currentRoles = computed(() => saved.value.find(p => p.name === ws.product)?.roles || [])

/* 没有任何 IP 的节点 —— 几乎总是它那个角色在模板里没配平面 */
const noIpNodes = computed(() =>
  nodes.value.filter(n => !Object.values(n.plane_ips || {}).some(v => (v || []).length)))
const noIpRoles = computed(() => [...new Set(noIpNodes.value.map(n => n.role_key || n.node_type))])

const onExpand = (row, rows) => { expanded.value = rows.map(r => r._uid) }
const expandRole = (row) => {
  if (!expanded.value.includes(row._uid)) expanded.value = [...expanded.value, row._uid]
}
const statusClass = (s) => ({ online: 'pass', degraded: 'warn', offline: 'fail' }[s] || 'idle')
const total = (m) => Object.values(m.counts || {}).reduce((a, b) => a + (Number(b) || 0), 0)

let uid = 0
const nextUid = () => `r${++uid}`

/*
 * 新角色默认就带上管理面和控制面, 网段沿用同产品里已有角色的 ——
 * 同一个产品的管理面 / 控制面几乎总是同一个网段。
 *
 * 之前默认是 planes: [], 而平面的配置藏在表格的展开行里, 很容易整行没配就保存:
 * 节点照样建出来, 但 IP 全是空的(IP 全部由平面网段生成), 组网图也是一片空白。
 */
const emptyRole = (product = null) => {
  const borrow = (plane) => {
    for (const r of (product?.roles || [])) {
      const hit = (r.planes || []).find(p => p.plane === plane)
      if (hit && (hit.prefixes || []).some(x => x)) return [...hit.prefixes]
    }
    return ['']
  }
  return {
    _uid: nextUid(),
    key: '', label: '', node_type: 'slave', hostname_prefix: 'node', role: '',
    hostname_start: 1, ip_start: 1,
    planes: [
      { plane: 'management', prefixes: borrow('management'), protocol: '', bandwidth: '', switch: '' },
      { plane: 'control', prefixes: borrow('control'), protocol: '', bandwidth: '', switch: '' },
    ],
    checks: ['ping'],
    os_version: '', cpu_cores: null, memory_gb: null, disk_gb: null, note: '',
  }
}

const hasPlane = (role, key) => (role.planes || []).some(p => p.plane === key)
const planeOf = (role, key) => (role.planes || []).find(p => p.plane === key) || { prefixes: [] }
const togglePlane = (role, key, on) => {
  if (on) role.planes.push({ plane: key, prefixes: [''], protocol: '', bandwidth: '', switch: '' })
  else role.planes = role.planes.filter(p => p.plane !== key)
}

const addProduct = () => {
  const role = emptyRole()
  draft.value.push({ name: '', description: '', roles: [role], machine_types: [] })
  activeProduct.value = String(draft.value.length - 1)
  expanded.value = [role._uid]
}

/** 加角色 —— 顺手展开这一行, 平面和网段就在里面, 不配的话节点不会有 IP */
const addRole = (product) => {
  const role = emptyRole(product)
  product.roles.push(role)
  expanded.value = [...expanded.value, role._uid]
}
const addMachine = (p) => {
  const counts = {}
  p.roles.forEach(r => { if (r.key) counts[r.key] = 0 })
  p.machine_types.push({ name: '', description: '', counts })
}

/* key 是拿来索引台数的, 所见即所存: 失焦时按后端那套规则规整一遍, 并把机台类型里
 * 的台数跟着改键 —— 不然改一下 key, 那一列的台数就在界面上归零了 */
const normalizeKey = (product, role) => {
  const before = role.key || ''
  const after = before.trim().toLowerCase().replace(/[^\w\u4e00-\u9fa5-]+/g, '-')
    .replace(/^[-_]+|[-_]+$/g, '')
  if (after === before) return
  role.key = after
  product.machine_types.forEach(m => {
    if (!after) return
    if (Object.prototype.hasOwnProperty.call(m.counts || {}, before)) {
      m.counts[after] = m.counts[before]
      delete m.counts[before]
    }
  })
}

const loadNodes = async () => {
  if (!ready.value) { nodes.value = []; return }
  try {
    const { data } = await axios.get('/api/workspace/nodes')
    nodes.value = data
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message)
  }
}

/* 表格的受控展开要一个不随输入变化的 row-key; key 是用户边打边改的, 不能拿来当它 */
const withUids = (products) => JSON.parse(JSON.stringify(products)).map(p => ({
  ...p,
  roles: (p.roles || []).map(r => ({ ...r, _uid: nextUid() })),
}))

const loadTemplates = async () => {
  try {
    const [{ data }, { data: m }] = await Promise.all([
      axios.get('/api/templates'),
      axios.get('/api/templates/meta'),
    ])
    saved.value = data.products || []
    meta.value = m
    tplProblems.value = data.problems || []
    tplWarnings.value = data.warnings || []
    draft.value = withUids(data.products || [])
  } catch (e) {
    tplError.value = e?.response?.data?.detail || e.message || '读取模板失败'
  }
}

const saveTemplates = async () => {
  tplError.value = ''
  tplProblems.value = []
  for (const p of draft.value) {
    if (!p.name.trim()) { tplError.value = '有产品没填名称'; return }
    const keys = p.roles.map(r => (r.key || '').trim())
    if (keys.some(k => !k)) { tplError.value = `产品「${p.name}」里有角色没填 key`; return }
    const dup = keys.filter((k, i) => keys.indexOf(k) !== i)
    if (dup.length) { tplError.value = `产品「${p.name}」里 key 重复: ${[...new Set(dup)].join(', ')}`; return }
    // 节点的 IP 全部由平面网段生成。没配平面 / 没填网段就保存, 存下去不报错, 但
    // 节点会没有 IP、组网图会是空的 —— 在这儿挡住, 并把那一行展开给人看
    for (const r of p.roles) {
      const name = r.label || r.key
      if (!(r.planes || []).length) {
        expandRole(r)
        tplError.value = `产品「${p.name}」的角色「${name}」没勾任何平面, 这样生成的节点不会有 IP, 组网图也画不出来`
        return
      }
      for (const pl of r.planes) {
        if (!(pl.prefixes || []).some(x => String(x || '').trim())) {
          expandRole(r)
          tplError.value = `产品「${p.name}」的角色「${name}」勾了「${PLANE_LABEL[pl.plane] || pl.plane}」但没填网段前缀, 这个平面不会生成 IP`
          return
        }
      }
    }
  }
  saving.value = true
  try {
    const payload = {
      products: draft.value.map(p => ({
        ...p,
        roles: p.roles.map(({ _uid, ...r }) => r),   // _uid 是界面自己用的, 不入库
      })),
    }
    const { data } = await axios.put('/api/templates', payload)
    saved.value = data.products || []
    tplWarnings.value = data.warnings || []
    draft.value = withUids(data.products || [])
    await loadWorkspace({ force: true })

    // 存完顺手把节点对齐一遍 —— 改了模板还要自己想起来去点「重新加载」, 中间那段
    // 时间里节点表和模板是不一致的, 人看到的就是"IP 没按模板生成"
    let synced = null
    if (ready.value) {
      try {
        synced = await reloadNodes()
        await loadNodes()
      } catch (e) { /* 模板存住了才是关键, 对齐失败就让人自己点一下「重新加载」 */ }
    }
    const bits = []
    if (synced?.created?.length) bits.push(`新增 ${synced.created.length}`)
    if (synced?.updated?.length) bits.push(`更新 ${synced.updated.length}`)
    if (synced?.removed?.length) bits.push(`移除 ${synced.removed.length}`)
    ElMessage.success(
      !ready.value ? '模板已保存。左上角「机台」里选一个机台类型, 节点就按模板加载出来'
      : bits.length ? `模板已保存, 当前机台的节点已对齐: ${bits.join(' · ')}`
      : '模板已保存, 当前机台的节点已经和模板一致'
    )
  } catch (e) {
    tplError.value = e?.response?.data?.detail || e.message || '保存失败'
  } finally {
    saving.value = false
  }
}

const reload = async () => {
  reloading.value = true
  try {
    const data = await reloadNodes()
    await loadNodes()
    const bits = []
    if (data.created?.length) bits.push(`新增 ${data.created.length}`)
    if (data.updated?.length) bits.push(`更新 ${data.updated.length}`)
    if (data.removed?.length) bits.push(`移除 ${data.removed.length}`)
    ElMessage.success(bits.length ? `已对齐模板: ${bits.join(' · ')}` : '已经和模板一致, 无需改动')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message)
  } finally {
    reloading.value = false
  }
}

const roleOf = (key) => currentRoles.value.find(r => r.key === key)

/*
 * 对话框里要列哪几个平面、每个平面几个口 —— 以模板里那个角色的声明为准,
 * 再并上这台节点上已经有的(角色被改过、手工加的口也不能弄丢)。
 *
 * 认不出角色时(角色删了、手工加的节点)四个平面全给出来, 否则没地方填。
 */
const nodePlanes = computed(() => {
  const role = roleOf(nodeForm.value.role_key)
  const have = nodeForm.value.plane_ips || {}
  let keys = (role?.planes || []).map(p => p.plane)
  Object.keys(have).forEach(p => { if (!keys.includes(p)) keys.push(p) })
  if (!keys.length) keys = [...PLANE_KEYS]
  return PLANE_KEYS.filter(p => keys.includes(p)).map(p => {
    const spec = (role?.planes || []).find(x => x.plane === p)
    return {
      plane: p,
      label: PLANE_LABEL[p],
      protocol: spec?.protocol || '',
      // 用模板的网段前缀当占位符, 填的时候不用回去翻模板
      placeholders: (spec?.prefixes || []).map(x => (x ? `${String(x).replace(/\.$/, '')}.x` : '')),
    }
  })
})

/** 按角色把每个平面的口数补齐到模板声明的数量, 已填的值原样留着 */
const fitNics = () => {
  const role = roleOf(nodeForm.value.role_key)
  const planes = { ...(nodeForm.value.plane_ips || {}) }
  Object.keys(planes).forEach(p => { planes[p] = [...(planes[p] || [])] })
  ;(role?.planes || []).forEach(spec => {
    const want = Math.max(1, (spec.prefixes || []).length)
    const arr = planes[spec.plane] || []
    while (arr.length < want) arr.push('')
    planes[spec.plane] = arr
  })
  PLANE_KEYS.forEach(p => { if (!planes[p]) planes[p] = [] })
  nodeForm.value.plane_ips = planes
}

const openNode = (row = null) => {
  nodeForm.value = row
    ? { ...row, plane_ips: JSON.parse(JSON.stringify(row.plane_ips || {})) }
    : { hostname: '', role_key: currentRoles.value[0]?.key || '', node_type: '',
        os_version: '', plane_ips: {} }
  onNodeRole()
  nodeOpen.value = true
}

const onNodeRole = () => {
  const role = roleOf(nodeForm.value.role_key)
  if (role) {
    if (!nodeForm.value.node_type) nodeForm.value.node_type = role.node_type
    if (!nodeForm.value.os_version) nodeForm.value.os_version = role.os_version || ''
  }
  fitNics()
}

const saveNode = async () => {
  if (!nodeForm.value.hostname?.trim()) { ElMessage.warning('填一个主机名'); return }
  savingNode.value = true
  try {
    // IP 的正主是 plane_ips —— 扁平字段(mgmt_ip / ctrl_ip / data_ip)由后端按第一个口
    // 同步, 这边不用也不该自己拼
    const planeIps = {}
    Object.entries(nodeForm.value.plane_ips || {}).forEach(([plane, ips]) => {
      const clean = (ips || []).map(x => String(x || '').trim()).filter(Boolean)
      if (clean.length) planeIps[plane] = clean
    })
    const role = roleOf(nodeForm.value.role_key)
    const dataPlane = (role?.planes || []).find(p => p.plane.startsWith('data') && planeIps[p.plane])
    const payload = {
      hostname: nodeForm.value.hostname.trim(),
      node_type: nodeForm.value.node_type || nodeForm.value.role_key || 'slave',
      role_key: nodeForm.value.role_key || null,
      product: ws.product,
      machine_type: ws.machineType,
      plane_ips: planeIps,
      data_protocol: dataPlane?.protocol || nodeForm.value.data_protocol || null,
      os_version: nodeForm.value.os_version || null,
    }
    if (nodeForm.value.id) await axios.put(`/api/nodes/${nodeForm.value.id}`, payload)
    else await axios.post('/api/nodes', payload)
    nodeOpen.value = false
    await loadNodes()
    ElMessage.success('已保存')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || '保存失败')
  } finally {
    savingNode.value = false
  }
}

// ── 导入 / 导出 nodes.json ──────────────────────────────────────────────────

const openImport = () => {
  importFile.value = null
  importPreview.value = null
  importError.value = ''
  removeMissing.value = false
  importOpen.value = true
  if (fileInput.value) fileInput.value.value = ''
}

const onPick = (e) => {
  importFile.value = e.target.files?.[0] || null
  importPreview.value = null
  importError.value = ''
  if (importFile.value) preview()
}

/** 先只看会改什么 —— 一条都不写库 */
const preview = async () => {
  if (!importFile.value) return
  importing.value = true
  importError.value = ''
  try {
    const form = new FormData()
    form.append('file', importFile.value)
    const { data } = await axios.post('/api/workspace/nodes/import?dry_run=true', form)
    importPreview.value = data
  } catch (e) {
    importPreview.value = null
    importError.value = e?.response?.data?.detail || e.message || '解析失败'
  } finally {
    importing.value = false
  }
}

const doImport = async () => {
  if (!importFile.value) return
  importing.value = true
  importError.value = ''
  try {
    const form = new FormData()
    form.append('file', importFile.value)
    const { data } = await axios.post(
      `/api/workspace/nodes/import?dry_run=false&remove_missing=${removeMissing.value}`, form)
    const a = data.applied || {}
    const bits = []
    if (a.created?.length) bits.push(`新增 ${a.created.length}`)
    if (a.updated?.length) bits.push(`更新 ${a.updated.length}`)
    if (a.removed?.length) bits.push(`删除 ${a.removed.length}`)
    importOpen.value = false
    await Promise.all([loadNodes(), loadWorkspace({ force: true })])
    ElMessage.success(bits.length ? `已导入: ${bits.join(' · ')}` : '文件和现在的节点一致, 没有改动')
  } catch (e) {
    importError.value = e?.response?.data?.detail || e.message || '导入失败'
  } finally {
    importing.value = false
  }
}

/** 存一份 JSON 到本地 —— 导模板和导 nodes.json 共用 */
const downloadJson = (data, name) => {
  const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name.replace(/[\\/:*?"<>|\s]+/g, '_')
  a.click()
  URL.revokeObjectURL(url)
}

// ── 导入 / 导出模板 ─────────────────────────────────────────────────────────
// 模板才是要在机器之间搬的那份东西。节点是照着它生成的产物, 所以导完模板顺手把
// 当前机台的节点对齐一遍 —— 不然人看到的又是"模板导进来了, IP 没跟着变"

const openTplImport = () => {
  tplImpFile.value = null
  tplImpPreview.value = null
  tplImpError.value = ''
  tplImpOpen.value = true
}

const onTplPick = (e) => {
  tplImpFile.value = e.target.files?.[0] || null
  tplImpPreview.value = null
  tplImpError.value = ''
  if (tplImpFile.value) tplPreview()
}

const tplPost = async (dryRun) => {
  const form = new FormData()
  form.append('file', tplImpFile.value)
  const { data } = await axios.post(
    `/api/templates/import?dry_run=${dryRun}&mode=${tplImpMode.value}`, form)
  return data
}

const tplPreview = async () => {
  if (!tplImpFile.value) return
  tplImporting.value = true
  tplImpError.value = ''
  try {
    tplImpPreview.value = await tplPost(true)
  } catch (e) {
    tplImpPreview.value = null
    tplImpError.value = e?.response?.data?.detail || e.message || '解析失败'
  } finally {
    tplImporting.value = false
  }
}

const doTplImport = async () => {
  if (!tplImpFile.value) return
  tplImporting.value = true
  tplImpError.value = ''
  try {
    const data = await tplPost(false)
    const bits = []
    if (data.summary.create) bits.push(`新增 ${data.summary.create}`)
    if (data.summary.update) bits.push(`覆盖 ${data.summary.update}`)
    if (data.summary.dropped) bits.push(`删掉 ${data.summary.dropped}`)
    tplImpOpen.value = false

    await loadTemplates()
    await loadWorkspace({ force: true })
    // 导进来的产品/机台类型可能和原来选的不是一个, resolve() 会落到第一个可用的,
    // 这里跟着它把节点对齐过来
    let synced = null
    if (ready.value) {
      try {
        synced = await reloadNodes()
        await loadNodes()
      } catch (e) { /* 模板导进去了才是关键, 对齐失败就让人自己点「重新加载」 */ }
    }
    const nodeBits = []
    if (synced?.created?.length) nodeBits.push(`新增 ${synced.created.length}`)
    if (synced?.updated?.length) nodeBits.push(`更新 ${synced.updated.length}`)
    if (synced?.removed?.length) nodeBits.push(`移除 ${synced.removed.length}`)
    ElMessage.success(
      !bits.length ? '文件和现在的模板一致, 没有改动'
      : `模板已导入: ${bits.join(' · ')}` +
        (nodeBits.length ? `; 当前机台的节点已对齐: ${nodeBits.join(' · ')}` : '')
    )
  } catch (e) {
    tplImpError.value = e?.response?.data?.detail || e.message || '导入失败'
  } finally {
    tplImporting.value = false
  }
}

const exportTemplates = async (product) => {
  try {
    const { data } = await axios.get('/api/templates/export',
      { params: product ? { product } : {} })
    downloadJson(data, `node_templates-${product || 'all'}.json`)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || '导出失败')
  }
}

const exportNodes = async () => {
  try {
    const { data } = await axios.get('/api/workspace/nodes/export')
    downloadJson(data, `nodes-${ws.machineType || 'export'}.json`)
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message || '导出失败')
  }
}

const removeNode = async (row) => {
  try {
    await ElMessageBox.confirm(
      `删除节点「${row.hostname}」? 如果它是模板生成的, 下次「重新加载」会再出现。`,
      '确认', { type: 'warning' })
  } catch (e) {
    return
  }
  try {
    await axios.delete(`/api/nodes/${row.id}`)
    await loadNodes()
    ElMessage.success('已删除')
  } catch (e) {
    ElMessage.error(e?.response?.data?.detail || e.message)
  }
}

watch(() => `${ws.product}/${ws.machineType}`, loadNodes)

onMounted(() => {
  loadWorkspace()
  loadNodes()
  loadTemplates()
})
</script>

<style scoped>
.machines { display: flex; flex-direction: column; }
.spacer { flex-grow: 1; }
.tag-bad {
  margin-left: 3px;
  padding: 0 4px;
  border-radius: 3px;
  background: var(--cm-crit-bg);
  color: var(--cm-crit);
  font-size: 10px;
  font-weight: 700;
}

.tag-bad-link {
  color: var(--cm-crit);
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
}

.issue { font-size: 12.5px; line-height: 1.8; }

.imp-hint {
  margin: 0 0 12px;
  font-size: 12.5px;
  line-height: 1.9;
  color: var(--cm-text-2);
}
.imp-hint code {
  padding: 1px 5px;
  border-radius: 4px;
  background: var(--cm-surface-2);
  font-family: var(--cm-mono);
  font-size: 11.5px;
}
.imp-pick {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.imp-file { font-size: 12px; color: var(--cm-text-2); }
.imp-sum {
  display: flex;
  gap: 8px;
  margin: 10px 0;
}
.imp-changed {
  margin-left: 4px;
  padding: 0 4px;
  border-radius: 3px;
  background: var(--cm-warn-bg);
  color: var(--cm-warn);
  font-size: 10px;
  font-weight: 700;
}
.imp-notes {
  margin-top: 10px;
  padding: 8px 12px;
  border: 1px solid var(--cm-warn-line);
  border-radius: var(--cm-radius-sm);
  background: var(--cm-warn-bg);
}
.imp-note { font-size: 12px; line-height: 1.85; color: var(--cm-warn); }
.imp-missing {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
  margin-top: 12px;
  font-size: 12px;
}
.warn-text { color: var(--cm-crit); font-weight: 600; }
.imp-mode {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
  font-size: 12px;
}
/* 「从 nodes.json 反填」是兜底入口, 正路是改模板再「重新加载」 —— 排版上也别抢戏 */
.rescue { margin-left: 4px; font-size: 12px; color: var(--cm-text-3); }

.nic-list { width: 100%; }
.nic-line {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.nic-foot {
  display: flex;
  align-items: center;
  gap: 10px;
}
.nic-proto {
  font-size: 11px;
  font-weight: 700;
  color: var(--cm-text-3);
}

.muted { color: var(--cm-text-3); font-size: 12px; }
.bold { font-weight: 700; color: var(--cm-text); }

.pane { display: flex; flex-direction: column; gap: 14px; }
.bar { display: flex; align-items: center; gap: 12px; padding: 12px 18px; }
.bar-title { font-size: 14px; font-weight: 700; color: var(--cm-text); }
.bar-sub { font-size: 12px; color: var(--cm-text-2); }

.ip-cell { display: flex; flex-direction: column; gap: 2px; align-items: flex-start; }
.ip { font-size: 12px; font-weight: 600; }

.prod { display: flex; flex-direction: column; gap: 14px; }
.row { display: flex; align-items: center; gap: 10px; }
.sub { display: flex; align-items: baseline; gap: 10px; }
.sub-title { font-size: 13px; font-weight: 700; color: var(--cm-text); }
.sub-hint { font-size: 12px; color: var(--cm-text-2); }

.expand { display: flex; flex-direction: column; gap: 16px; padding: 12px 18px; }
.exp-block { display: flex; flex-direction: column; gap: 8px; }
.exp-title { font-size: 13px; font-weight: 700; color: var(--cm-text); }
.exp-hint { font-size: 12px; color: var(--cm-text-2); line-height: 1.6; }

.plane-block {
  padding: 9px 12px;
  background: var(--cm-bg);
  border: 1px solid var(--cm-border-light);
  border-radius: 8px;
}
.plane-head { display: flex; align-items: center; gap: 14px; }
.nics { display: flex; flex-direction: column; gap: 6px; margin: 8px 0 2px 24px; }
.nic { display: flex; align-items: center; gap: 10px; }
.nic-no { font-size: 12px; color: var(--cm-text-3); width: 52px; }
.nic-eg { font-size: 11px; color: var(--cm-text-3); }
.plane-tag { font-size: 12px; font-weight: 700; margin-right: 8px; }
</style>

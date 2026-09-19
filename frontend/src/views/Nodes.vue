<template>
  <div class="nodes-view">
    <!-- 节点列表 -->
    <el-card>
      <template #header>
        <div class="card-header">
          <span>节点列表 (三平面网络)</span>
          <div class="header-actions">
            <el-select v-model="filterType" placeholder="节点类型" clearable style="width: 130px">
              <el-option label="Master" value="master" />
              <el-option label="Slave" value="slave" />
              <el-option label="SubSwath" value="subswath" />
              <el-option label="GStorage" value="gstorage" />
              <el-option label="Sensor" value="sensor" />
            </el-select>
            <el-select v-model="filterMachine" placeholder="机台" clearable style="width: 150px">
              <el-option v-for="m in machineOptions" :key="m" :label="m" :value="m" />
            </el-select>
            <el-select v-model="filterStatus" placeholder="状态" clearable style="width: 100px">
              <el-option label="在线" value="online" />
              <el-option label="离线" value="offline" />
              <el-option label="告警" value="warning" />
            </el-select>
            <el-button type="primary" @click="loadNodes">
              <el-icon><Refresh /></el-icon>
              刷新
            </el-button>
            <el-button type="warning" @click="forceSyncFromJson" :loading="syncing">
              从规划重新同步
            </el-button>
            <el-button type="info" @click="openDebug">
              诊断
            </el-button>
            <el-button type="success" @click="openAdd">
              <el-icon><Plus /></el-icon>
              新增节点
            </el-button>
            <el-button type="success" plain @click="openApply">
              <el-icon><Files /></el-icon>
              按机台添加
            </el-button>
          </div>
        </div>
      </template>

      <el-table :data="filteredNodes" stripe>
        <el-table-column prop="hostname" label="主机名" width="130" />
        <el-table-column label="项目 / 机台" width="150">
          <template #default="{ row }">
            <template v-if="row.machine_type">
              <div class="mt-name">{{ row.machine_type }}</div>
              <div class="role-text">{{ row.project }}</div>
            </template>
            <span v-else class="role-text">—</span>
          </template>
        </el-table-column>
        <el-table-column label="类型 / 角色" width="110">
          <template #default="{ row }">
            <el-tag :type="nodeTypeTag(row.node_type)" size="small">{{ row.node_type }}</el-tag>
            <div v-if="row.role" class="role-text">{{ row.role }}</div>
          </template>
        </el-table-column>
        <el-table-column label="管理面 (GE)" width="180">
          <template #default="{ row }">
            <div class="plane-info">
              <span class="ip">{{ row.mgmt_ip || '-' }}</span>
              <el-tag :type="getStatusType(row.status)" size="small">{{ row.status }}</el-tag>
            </div>
            <div class="sub-info">BMC: {{ row.bmc_ip || '-' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="控制面 (10GE)" width="150">
          <template #default="{ row }">
            <div class="plane-info">
              <span class="ip">{{ row.ctrl_ip || '-' }}</span>
              <el-tag :type="getStatusType(row.ctrl_status)" size="small">
                {{ row.ctrl_status || 'offline' }}
              </el-tag>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="数据面 (100GE)" width="180">
          <template #default="{ row }">
            <div class="plane-info">
              <span class="ip">{{ row.data_ip || '-' }}</span>
              <el-tag :type="getStatusType(row.data_status)" size="small">
                {{ row.data_status || 'offline' }}
              </el-tag>
            </div>
            <div class="sub-info">{{ row.data_protocol || '-' }}</div>
          </template>
        </el-table-column>
        <el-table-column prop="os_version" label="系统版本" width="130" />
        <el-table-column label="配置" width="150">
          <template #default="{ row }">
            <span>{{ row.cpu_cores || '-' }}核 / {{ row.memory_gb || '-' }}G / {{ row.disk_gb || '-' }}G</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="300" fixed="right">
          <template #default="{ row }">
            <el-button size="small" type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button size="small" @click="checkNetwork(row)">网络检查</el-button>
            <el-button size="small" type="warning" @click="showPowerDialog(row)">电源</el-button>
            <el-button size="small" type="danger" @click="deleteNode(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 新增 / 编辑节点对话框 -->
    <!-- ── 按机台类型批量添加 ─────────────────────────────────────────── -->
    <el-dialog v-model="applyDialogVisible" title="按机台类型添加节点" width="900px" :close-on-click-modal="false">
      <div class="tpl-bar">
        <el-select v-model="selectedProject" placeholder="选择项目" style="width: 240px" @change="onProjectChange">
          <el-option v-for="p in projects" :key="p.name" :label="p.name" :value="p.name" />
        </el-select>
        <el-select
          v-model="selectedMachine"
          placeholder="选择机台类型"
          style="width: 240px"
          :disabled="!currentProject"
          @change="loadPreview"
        >
          <el-option
            v-for="m in currentProject?.machine_types || []"
            :key="m.name"
            :label="m.name"
            :value="m.name"
          />
        </el-select>
        <span class="tpl-desc">{{ currentMachine?.description || currentProject?.description }}</span>
        <el-button link type="primary" @click="openManage">管理模板</el-button>
      </div>

      <el-alert
        v-for="(c, i) in preview.conflicts"
        :key="i"
        :title="c"
        type="warning"
        :closable="false"
        show-icon
        class="tpl-alert"
      />

      <el-table
        v-loading="previewLoading"
        :data="preview.nodes"
        stripe
        size="small"
        max-height="380"
        empty-text="选择项目和机台类型后显示将创建的节点"
      >
        <el-table-column prop="hostname" label="主机名" width="120" />
        <el-table-column prop="node_type" label="类型" width="95" />
        <el-table-column prop="bmc_ip" label="BMC / 管理面" width="130" />
        <el-table-column prop="ctrl_ip" label="控制面" width="130" />
        <el-table-column prop="data_ip" label="数据面" width="130" />
        <el-table-column prop="data_protocol" label="协议" width="80" />
        <el-table-column label="规格">
          <template #default="{ row }">
            <span class="tpl-spec">
              {{ row.cpu_cores ? row.cpu_cores + 'C' : '' }}
              {{ row.memory_gb ? '/ ' + row.memory_gb + 'G' : '' }}
              {{ row.disk_gb ? '/ ' + row.disk_gb + 'G' : '' }}
            </span>
          </template>
        </el-table-column>
      </el-table>

      <template #footer>
        <span class="tpl-total">
          共 {{ preview.total }} 台，IP 已避开库中已占用的地址；创建后节点会记录所属项目与机台类型
        </span>
        <el-button @click="applyDialogVisible = false">取消</el-button>
        <el-button type="primary" :disabled="!preview.total" :loading="applying" @click="applyTemplate">
          创建这 {{ preview.total }} 台
        </el-button>
      </template>
    </el-dialog>

    <!-- ── 模板维护: 项目 → 机台类型 ──────────────────────────────────── -->
    <el-dialog v-model="manageDialogVisible" title="节点模板" width="1280px" :close-on-click-modal="false">
      <el-alert
        type="info"
        :closable="false"
        show-icon
        class="tpl-alert"
        title="项目定义本项目共用的角色配置（网段、起始序号、协议、规格），机台类型只定义各角色各几台 —— 同一项目下不同机台类型的区别就在服务器台数。模板存后端 node_templates.json，不入数据库。"
      />

      <div class="tpl-bar">
        <el-select v-model="editingProjectIndex" placeholder="选择项目" style="width: 260px">
          <el-option
            v-for="(p, i) in draftProjects"
            :key="i"
            :label="p.name || '(未命名项目)'"
            :value="i"
          />
        </el-select>
        <el-button @click="addProject">新增项目</el-button>
        <el-button type="danger" plain :disabled="editingProjectIndex === null" @click="removeProject">
          删除此项目
        </el-button>
      </div>

      <template v-if="editingProject">
        <el-row :gutter="16" class="tpl-meta">
          <el-col :span="8">
            <el-input v-model="editingProject.name" placeholder="项目名称" />
          </el-col>
          <el-col :span="16">
            <el-input v-model="editingProject.description" placeholder="项目说明（可选）" />
          </el-col>
        </el-row>

        <el-divider content-position="left">角色配置（本项目共用）</el-divider>
        <el-table :data="editingProject.roles" size="small" border max-height="260">
          <el-table-column label="节点类型" width="112">
            <template #default="{ row }">
              <el-select v-model="row.node_type" size="small">
                <el-option label="Master" value="master" />
                <el-option label="Slave" value="slave" />
                <el-option label="SubSwath" value="subswath" />
                <el-option label="GStorage" value="gstorage" />
                <el-option label="Sensor" value="sensor" />
                <el-option label="Acquisition" value="acquisition" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="主机名前缀" width="118">
            <template #default="{ row }">
              <el-input v-model="row.hostname_prefix" size="small" @change="syncRoleKeys" />
            </template>
          </el-table-column>
          <el-table-column label="主机名起始" width="98">
            <template #default="{ row }">
              <el-input-number v-model="row.hostname_start" :min="0" size="small" controls-position="right" style="width:100%" />
            </template>
          </el-table-column>
          <el-table-column label="BMC 网段" width="116">
            <template #default="{ row }"><el-input v-model="row.bmc_prefix" size="small" placeholder="172.16.0." /></template>
          </el-table-column>
          <el-table-column label="控制面网段" width="116">
            <template #default="{ row }"><el-input v-model="row.ctrl_prefix" size="small" placeholder="172.16.3." /></template>
          </el-table-column>
          <el-table-column label="数据面网段" width="116">
            <template #default="{ row }"><el-input v-model="row.data_prefix" size="small" placeholder="100.1.1." /></template>
          </el-table-column>
          <el-table-column label="IP 起始" width="86">
            <template #default="{ row }">
              <el-input-number v-model="row.ip_start" :min="0" :max="255" size="small" controls-position="right" style="width:100%" />
            </template>
          </el-table-column>
          <el-table-column label="协议" width="92">
            <template #default="{ row }">
              <el-select v-model="row.data_protocol" size="small" clearable>
                <el-option label="DPDK" value="DPDK" />
                <el-option label="RDMA" value="RDMA" />
              </el-select>
            </template>
          </el-table-column>
          <el-table-column label="核" width="78">
            <template #default="{ row }"><el-input-number v-model="row.cpu_cores" :min="0" :controls="false" size="small" style="width:100%" /></template>
          </el-table-column>
          <el-table-column label="内存G" width="84">
            <template #default="{ row }"><el-input-number v-model="row.memory_gb" :min="0" :controls="false" size="small" style="width:100%" /></template>
          </el-table-column>
          <el-table-column label="磁盘G" width="96">
            <template #default="{ row }"><el-input-number v-model="row.disk_gb" :min="0" :controls="false" size="small" style="width:100%" /></template>
          </el-table-column>
          <el-table-column label="操作" width="62">
            <template #default="{ $index }">
              <el-button link type="danger" size="small" @click="removeRole($index)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-button size="small" class="tpl-addrole" @click="addRole">添加一个角色</el-button>

        <el-divider content-position="left">机台类型（只填各角色台数）</el-divider>
        <el-table :data="editingProject.machine_types" size="small" border max-height="260">
          <el-table-column label="机台类型" width="180">
            <template #default="{ row }"><el-input v-model="row.name" size="small" placeholder="如 KX-2000" /></template>
          </el-table-column>
          <el-table-column
            v-for="r in editingProject.roles"
            :key="r.hostname_prefix"
            :label="r.hostname_prefix"
            width="96"
          >
            <template #default="{ row }">
              <el-input-number
                :model-value="row.counts[r.hostname_prefix] ?? 0"
                @update:model-value="v => row.counts[r.hostname_prefix] = v ?? 0"
                :min="0"
                :max="255"
                :controls="false"
                size="small"
                style="width:100%"
              />
            </template>
          </el-table-column>
          <el-table-column label="说明">
            <template #default="{ row }"><el-input v-model="row.description" size="small" placeholder="可选" /></template>
          </el-table-column>
          <el-table-column label="操作" width="62">
            <template #default="{ $index }">
              <el-button link type="danger" size="small" @click="editingProject.machine_types.splice($index, 1)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-button size="small" class="tpl-addrole" @click="addMachineType">添加一个机台类型</el-button>
      </template>

      <template #footer>
        <el-button @click="manageDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingTemplates" @click="saveTemplates">保存模板</el-button>
      </template>
    </el-dialog>

    <el-dialog
      v-model="editDialogVisible"
      :title="editMode === 'add' ? '新增节点' : '编辑节点'"
      width="700px"
      :close-on-click-modal="false"
    >
      <el-form :model="editForm" :rules="editRules" ref="editFormRef" label-width="110px" size="default">

        <el-divider content-position="left">基本信息</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="主机名" prop="hostname">
              <el-input v-model="editForm.hostname" placeholder="如 master-01" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="节点类型" prop="node_type">
              <el-select v-model="editForm.node_type" style="width:100%">
                <el-option label="Master" value="master" />
                <el-option label="Slave" value="slave" />
                <el-option label="SubSwath" value="subswath" />
                <el-option label="GStorage" value="gstorage" />
                <el-option label="Sensor" value="sensor" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="角色">
              <el-input v-model="editForm.role" placeholder="可选，如 compute" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">管理面 (GE)</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="管理面 IP">
              <el-input v-model="editForm.mgmt_ip" placeholder="172.16.0.x" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="管理面 MAC">
              <el-input v-model="editForm.mgmt_mac" placeholder="aa:bb:cc:dd:ee:ff" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="BMC IP">
              <el-input v-model="editForm.bmc_ip" placeholder="172.16.0.x" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="BMC MAC">
              <el-input v-model="editForm.bmc_mac" placeholder="aa:bb:cc:dd:ee:ff" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">控制面 (10GE)</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="控制面 IP">
              <el-input v-model="editForm.ctrl_ip" placeholder="172.16.3.x" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="控制面 MAC">
              <el-input v-model="editForm.ctrl_mac" placeholder="aa:bb:cc:dd:ee:ff" />
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">数据面 (100GE)</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="数据面 IP">
              <el-input v-model="editForm.data_ip" placeholder="200.1.1.x / 100.1.1.x" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="数据面 MAC">
              <el-input v-model="editForm.data_mac" placeholder="aa:bb:cc:dd:ee:ff" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="数据协议">
              <el-select v-model="editForm.data_protocol" clearable style="width:100%">
                <el-option label="DPDK" value="DPDK" />
                <el-option label="RDMA" value="RDMA" />
              </el-select>
            </el-form-item>
          </el-col>
        </el-row>

        <el-divider content-position="left">硬件信息</el-divider>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="系统版本">
              <el-input v-model="editForm.os_version" placeholder="OpenEuler 22.03" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="CPU 核数">
              <el-input-number v-model="editForm.cpu_cores" :min="1" :precision="0" controls-position="right" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="内存 (GB)">
              <el-input-number v-model="editForm.memory_gb" :min="1" :precision="0" controls-position="right" style="width:100%" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="磁盘 (GB)">
              <el-input-number v-model="editForm.disk_gb" :min="1" :precision="0" controls-position="right" style="width:100%" />
            </el-form-item>
          </el-col>
        </el-row>

      </el-form>
      <template #footer>
        <el-button @click="editDialogVisible = false">取消</el-button>
        <el-button type="primary" @click="saveNode" :loading="saving">保存</el-button>
      </template>
    </el-dialog>

    <!-- 电源控制对话框 -->
    <el-dialog v-model="powerDialogVisible" title="电源控制" width="400px">
      <div class="power-controls">
        <p>节点: {{ selectedNode?.hostname }}</p>
        <p>BMC: {{ selectedNode?.bmc_ip }}</p>
        <div class="power-buttons">
          <el-button type="success" @click="powerControl('on')">开机</el-button>
          <el-button type="danger" @click="powerControl('off')">关机</el-button>
          <el-button type="warning" @click="powerControl('reset')">重启</el-button>
          <el-button @click="powerControl('status')">查询状态</el-button>
        </div>
      </div>
    </el-dialog>

    <!-- 网络检查结果对话框 -->
    <el-dialog v-model="networkDialogVisible" title="三平面网络检查" width="500px">
      <div v-if="networkCheckResult" class="network-result">
        <div class="plane-check">
          <h4>管理面 (GE口)</h4>
          <p>IP: {{ networkCheckResult.planes.management.ip }}</p>
          <p>BMC IP: {{ networkCheckResult.planes.management.bmc_ip }}</p>
          <el-tag :type="networkCheckResult.planes.management.reachable ? 'success' : 'danger'">
            {{ networkCheckResult.planes.management.reachable ? '可达' : '不可达' }}
          </el-tag>
          <span v-if="networkCheckResult.planes.management.latency_ms">
            延迟: {{ networkCheckResult.planes.management.latency_ms }}ms
          </span>
        </div>
        <div class="plane-check">
          <h4>控制面 (10GE)</h4>
          <p>IP: {{ networkCheckResult.planes.control.ip }}</p>
          <el-tag :type="networkCheckResult.planes.control.reachable ? 'success' : 'danger'">
            {{ networkCheckResult.planes.control.reachable ? '可达' : '不可达' }}
          </el-tag>
          <span v-if="networkCheckResult.planes.control.latency_ms">
            延迟: {{ networkCheckResult.planes.control.latency_ms }}ms
          </span>
        </div>
        <div class="plane-check">
          <h4>数据面 (100GE)</h4>
          <p>IP: {{ networkCheckResult.planes.data.ip }}</p>
          <p>协议: {{ networkCheckResult.planes.data.protocol }}</p>
          <el-tag :type="networkCheckResult.planes.data.reachable ? 'success' : 'danger'">
            {{ networkCheckResult.planes.data.reachable ? '可达' : '不可达' }}
          </el-tag>
          <span v-if="networkCheckResult.planes.data.throughput_mbps">
            吞吐: {{ networkCheckResult.planes.data.throughput_mbps }}Mbps
          </span>
        </div>
      </div>
    </el-dialog>

    <!-- ══ 诊断面板 ══ -->
    <el-dialog v-model="debugDialogVisible" title="同步诊断" width="900px" top="5vh">
      <div v-if="debugLoading" style="padding:24px;text-align:center;color:#a0a0a0">加载中...</div>
      <div v-else-if="debugData" class="debug-panel">
        <el-alert
          :type="debugData.db.raw_count === debugData.nodes_json.entries ? 'success' : 'warning'"
          :title="`nodes.json: ${debugData.nodes_json.entries} 个节点 | DB(SQL): ${debugData.db.raw_count} | DB(ORM): ${debugData.db.orm_count}`"
          :closable="false"
          show-icon
          style="margin-bottom:14px"
        />
        <div class="debug-paths">
          <div><b>数据库文件</b>：<code>{{ debugData.database_path }}</code></div>
          <div><b>nodes.json</b>：<code>{{ debugData.nodes_json_path }}</code></div>
        </div>

        <el-collapse>
          <el-collapse-item :title="`nodes.json 中的 ${debugData.nodes_json.entries} 个节点`" name="nj">
            <el-table :data="debugData.nodes_json.hostnames" size="small" max-height="220">
              <el-table-column prop="hostname" label="主机名" width="160" />
              <el-table-column prop="role" label="角色" width="120" />
              <el-table-column prop="mac" label="MAC" />
            </el-table>
          </el-collapse-item>

          <el-collapse-item :title="`DB 中的 ${debugData.db.orm_count} 个节点 (ORM 解析后)`" name="db">
            <el-table :data="debugData.db.nodes" size="small" max-height="220">
              <el-table-column prop="id" label="ID" width="60" />
              <el-table-column prop="hostname" label="主机名" width="140" />
              <el-table-column prop="node_type" label="类型" width="100" />
              <el-table-column prop="status" label="状态" width="80" />
              <el-table-column prop="ctrl_ip" label="ctrl_ip" />
              <el-table-column prop="bmc_ip" label="bmc_ip" />
            </el-table>
            <div v-if="debugData.db.error" class="debug-err">DB 错误: {{ debugData.db.error }}</div>
          </el-collapse-item>

          <el-collapse-item :title="`nodes 表实际列 (${debugData.db.columns.length})`" name="cols">
            <code style="word-break:break-all;color:#8b949e">{{ debugData.db.columns.join(', ') }}</code>
            <div v-if="debugData.db.columns_error" class="debug-err">{{ debugData.db.columns_error }}</div>
          </el-collapse-item>
        </el-collapse>

        <div v-if="debugData.db.raw_count !== debugData.nodes_json.entries" class="debug-hint">
          <strong>判读：</strong>
          <ul>
            <li v-if="debugData.db.raw_count === 0">DB 真的是空的——sync 没有写入任何节点。可能原因：sync 调用根本没跑（旧后端未重启）、或 sync 内每条都抛了异常（看后端控制台 [sync][error] 日志）</li>
            <li v-else-if="debugData.db.raw_count !== debugData.db.orm_count">SQL count 和 ORM count 对不上——response_model 验证可能因某节点字段不合规失败</li>
            <li v-else>DB 有数据但前端没显示——刷新页面或检查 GET /api/nodes 返回</li>
          </ul>
        </div>
      </div>
      <div v-else class="debug-err">加载诊断信息失败</div>
      <template #footer>
        <el-button @click="loadDebug" :loading="debugLoading">重新加载</el-button>
        <el-button @click="debugDialogVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { Refresh, Plus, Files } from '@element-plus/icons-vue'
import axios from 'axios'
import { ElMessage, ElMessageBox } from 'element-plus'

const nodes = ref([])
const filterType = ref('')
const filterStatus = ref('')
const filterMachine = ref('')
const selectedNode = ref(null)

const powerDialogVisible = ref(false)
const networkDialogVisible = ref(false)
const networkCheckResult = ref(null)

// ── 节点模板: 项目 → 机台类型 ──────────────────────────────
// 模板存后端 node_templates.json, 不入库。项目定义共用的角色配置,
// 机台类型只定义各角色台数 —— 同项目下不同机台的区别就在服务器台数。
const applyDialogVisible = ref(false)
const manageDialogVisible = ref(false)
const projects = ref([])
const selectedProject = ref('')
const selectedMachine = ref('')
const preview = ref({ total: 0, nodes: [], conflicts: [] })
const previewLoading = ref(false)
const applying = ref(false)

const currentProject = computed(() =>
  projects.value.find(p => p.name === selectedProject.value) || null
)
const currentMachine = computed(() =>
  currentProject.value?.machine_types.find(m => m.name === selectedMachine.value) || null
)

const emptyPreview = () => ({ total: 0, nodes: [], conflicts: [] })

const loadTemplates = async () => {
  try {
    const { data } = await axios.get('/api/templates')
    projects.value = data.projects || []
  } catch (e) {
    ElMessage.error('加载模板失败: ' + (e.response?.data?.detail || e.message))
  }
}

const loadPreview = async () => {
  if (!selectedProject.value || !selectedMachine.value) {
    preview.value = emptyPreview()
    return
  }
  previewLoading.value = true
  try {
    const { data } = await axios.get('/api/templates/preview', {
      params: { project: selectedProject.value, machine_type: selectedMachine.value },
    })
    preview.value = data
  } catch (e) {
    preview.value = emptyPreview()
    ElMessage.error('预览失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    previewLoading.value = false
  }
}

// 换项目后原机台类型多半已不存在; 只有一个时直接选中, 省一次点击
const onProjectChange = async () => {
  const list = currentProject.value?.machine_types || []
  selectedMachine.value = list.length === 1 ? list[0].name : ''
  await loadPreview()
}

const openApply = async () => {
  preview.value = emptyPreview()
  selectedProject.value = ''
  selectedMachine.value = ''
  applyDialogVisible.value = true
  await loadTemplates()
  if (projects.value.length === 1) {
    selectedProject.value = projects.value[0].name
    await onProjectChange()
  }
}

const applyTemplate = async () => {
  applying.value = true
  try {
    const { data } = await axios.post('/api/templates/apply', {
      project: selectedProject.value,
      machine_type: selectedMachine.value,
    })
    ElMessage.success(`已创建 ${data.created} 台节点`)
    applyDialogVisible.value = false
    loadNodes()
  } catch (e) {
    ElMessage.error('创建失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    applying.value = false
  }
}

// ── 模板维护 ──────────────────────────────────────────────────
// draftProjects 是深拷贝的草稿, 保存成功前不影响 projects
const draftProjects = ref([])
const editingProjectIndex = ref(null)
const savingTemplates = ref(false)

const editingProject = computed(() =>
  editingProjectIndex.value === null ? null : draftProjects.value[editingProjectIndex.value] || null
)

const emptyRole = () => ({
  node_type: 'slave',
  hostname_prefix: 'node',
  _prev: 'node',
  role: '',
  data_protocol: '',
  bmc_prefix: '',
  ctrl_prefix: '',
  data_prefix: '',
  hostname_start: 1,
  ip_start: 1,
  os_version: '',
  cpu_cores: null,
  memory_gb: null,
  disk_gb: null,
})

const openManage = async () => {
  await loadTemplates()
  draftProjects.value = JSON.parse(JSON.stringify(projects.value))
  draftProjects.value.forEach(p => p.roles.forEach(r => { r._prev = r.hostname_prefix }))
  editingProjectIndex.value = draftProjects.value.length ? 0 : null
  manageDialogVisible.value = true
}

const addProject = () => {
  draftProjects.value.push({ name: '', description: '', roles: [emptyRole()], machine_types: [] })
  editingProjectIndex.value = draftProjects.value.length - 1
}

const removeProject = () => {
  if (editingProjectIndex.value === null) return
  draftProjects.value.splice(editingProjectIndex.value, 1)
  editingProjectIndex.value = draftProjects.value.length ? 0 : null
}

const addRole = () => {
  editingProject.value?.roles.push(emptyRole())
  syncRoleKeys()
}

const removeRole = (index) => {
  const p = editingProject.value
  if (!p) return
  const [gone] = p.roles.splice(index, 1)
  // 角色没了, 各机台类型里它的台数也一并清掉, 免得留下孤儿键
  if (gone) {
    p.machine_types.forEach(m => {
      delete m.counts[gone.hostname_prefix]
      if (gone._prev) delete m.counts[gone._prev]
    })
  }
}

// 角色以 hostname_prefix 为标识。前缀改名后必须把各机台类型的台数从旧键迁到新键,
// 否则台数会归零 —— 所以每个草稿角色记一个 _prev 存改名前的前缀。
// _prev 只在前端草稿里存在, 保存时剥掉。
const syncRoleKeys = () => {
  const p = editingProject.value
  if (!p) return

  // 1. 按 _prev → 当前前缀 迁移已有台数
  p.roles.forEach(r => {
    const prev = r._prev
    const now = r.hostname_prefix
    if (prev && prev !== now) {
      p.machine_types.forEach(m => {
        if (Object.prototype.hasOwnProperty.call(m.counts, prev)) {
          m.counts[now] = m.counts[prev]
          delete m.counts[prev]
        }
      })
    }
    r._prev = now
  })

  // 2. 补齐新角色的键、清掉已删角色留下的孤儿键
  const keys = p.roles.map(r => r.hostname_prefix)
  p.machine_types.forEach(m => {
    const next = {}
    keys.forEach(k => { next[k] = m.counts[k] ?? 0 })
    m.counts = next
  })
}

const addMachineType = () => {
  const p = editingProject.value
  if (!p) return
  const counts = {}
  p.roles.forEach(r => { counts[r.hostname_prefix] = 0 })
  p.machine_types.push({ name: '', description: '', counts })
}

const saveTemplates = async () => {
  savingTemplates.value = true
  try {
    syncRoleKeys()
    // _prev 只是前端用来追踪改名的, 不发给后端
    const payload = draftProjects.value.map(p => ({
      ...p,
      roles: p.roles.map(({ _prev, ...rest }) => rest),
    }))
    const { data } = await axios.put('/api/templates', { projects: payload })
    projects.value = data.projects || []
    ElMessage.success('模板已保存')
    manageDialogVisible.value = false
    // 改完模板后当前选择可能已失效, 重新核对
    if (!currentProject.value) {
      selectedProject.value = ''
      selectedMachine.value = ''
      preview.value = emptyPreview()
    } else if (!currentMachine.value) {
      selectedMachine.value = ''
      preview.value = emptyPreview()
    } else {
      loadPreview()
    }
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    savingTemplates.value = false
  }
}

// ── 新增/编辑 ─────────────────────────────────────────────────
const editDialogVisible = ref(false)
const editMode = ref('add')
const editFormRef = ref(null)
const saving = ref(false)

const emptyForm = () => ({
  hostname: '',
  node_type: 'slave',
  role: '',
  mgmt_ip: '',
  mgmt_mac: '',
  bmc_ip: '',
  bmc_mac: '',
  ctrl_ip: '',
  ctrl_mac: '',
  data_ip: '',
  data_mac: '',
  data_protocol: '',
  os_version: '',
  cpu_cores: null,
  memory_gb: null,
  disk_gb: null,
})

const editForm = ref(emptyForm())

const editRules = {
  hostname: [{ required: true, message: '请输入主机名', trigger: 'blur' }],
  node_type: [{ required: true, message: '请选择节点类型', trigger: 'change' }],
}

const openAdd = () => {
  editMode.value = 'add'
  editForm.value = emptyForm()
  editDialogVisible.value = true
}

const openEdit = (node) => {
  editMode.value = 'edit'
  editForm.value = { ...node }
  editDialogVisible.value = true
}

const saveNode = async () => {
  try {
    await editFormRef.value.validate()
  } catch {
    return
  }
  saving.value = true
  try {
    const payload = { ...editForm.value }
    // 清理空字符串为 null，避免覆盖已有数据
    Object.keys(payload).forEach(k => {
      if (payload[k] === '') payload[k] = null
    })
    if (editMode.value === 'add') {
      await axios.post('/api/nodes', payload)
      ElMessage.success('节点已新增')
    } else {
      await axios.put(`/api/nodes/${editForm.value.id}`, payload)
      ElMessage.success('节点已更新')
    }
    editDialogVisible.value = false
    loadNodes()
  } catch (e) {
    ElMessage.error('保存失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

const deleteNode = async (node) => {
  try {
    await ElMessageBox.confirm(
      `确认删除节点 "${node.hostname}"？此操作不可恢复。`,
      '删除确认',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }
    )
    await axios.delete(`/api/nodes/${node.id}`)
    ElMessage.success('节点已删除')
    loadNodes()
  } catch (e) {
    if (e !== 'cancel' && e?.message !== 'cancel') {
      ElMessage.error('删除失败: ' + (e.response?.data?.detail || e.message))
    }
  }
}

// ── 筛选 ──────────────────────────────────────────────────────
const filteredNodes = computed(() => {
  let result = nodes.value
  if (filterType.value) result = result.filter(n => n.node_type === filterType.value)
  if (filterMachine.value) result = result.filter(n => n.machine_type === filterMachine.value)
  if (filterStatus.value) result = result.filter(n => n.status === filterStatus.value)
  return result
})

// 机台筛选项取自现有节点, 而不是模板 —— 模板改了也不影响已建节点的归属
const machineOptions = computed(() =>
  [...new Set(nodes.value.map(n => n.machine_type).filter(Boolean))].sort()
)

// ── 样式辅助 ──────────────────────────────────────────────────
const nodeTypeTag = (type) => {
  const map = { master: 'danger', slave: 'info', subswath: 'warning', gstorage: 'success', sensor: '' }
  return map[type] ?? 'info'
}

const getStatusType = (status) => {
  const map = { online: 'success', offline: 'danger', warning: 'warning', deploying: 'info', error: 'danger' }
  return map[status] ?? 'info'
}

// ── 数据加载 ──────────────────────────────────────────────────
const loadNodes = async () => {
  try {
    const response = await axios.get('/api/nodes')
    nodes.value = response.data
  } catch (e) {
    ElMessage.error('获取节点列表失败')
  }
}

// ── 诊断面板 ────────────────────────────────────────────────
const debugDialogVisible = ref(false)
const debugLoading = ref(false)
const debugData = ref(null)
const openDebug = () => {
  debugDialogVisible.value = true
  loadDebug()
}
const loadDebug = async () => {
  debugLoading.value = true
  try {
    const res = await axios.get('/api/pxe/debug-state')
    debugData.value = res.data
  } catch (e) {
    debugData.value = null
    ElMessage.error('加载诊断失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    debugLoading.value = false
  }
}

// 从 pxe_data/nodes.json 强制同步到 DB (作为 IP 规划落库的应急/手动入口)
const syncing = ref(false)
const forceSyncFromJson = async () => {
  syncing.value = true
  try {
    const res = await axios.post('/api/pxe/nodes-json/sync-to-db')
    const d = res.data || {}
    ElMessage.success(
      `同步完成: 新建 ${d.created || 0} / 更新 ${d.updated || 0} / ` +
      `清理残留 ${d.deleted || 0}, 数据库共 ${d.db_total || 0} 个节点`
    )
    if (d.deleted && d.deleted_hostnames?.length) {
      console.warn('[sync] 清理规划残留:', d.deleted_hostnames)
    }
    if (d.skipped && d.skipped.length) {
      console.warn('[sync] 跳过的条目:', d.skipped)
      ElMessage.warning(`有 ${d.skipped.length} 个条目被跳过, 详见控制台`)
    }
    await loadNodes()
  } catch (e) {
    ElMessage.error('同步失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    syncing.value = false
  }
}

// ── 电源控制 ──────────────────────────────────────────────────
const showPowerDialog = (node) => {
  selectedNode.value = node
  powerDialogVisible.value = true
}

const powerControl = async (action) => {
  if (!selectedNode.value) return
  try {
    const response = await axios.post(`/api/ipmi/nodes/${selectedNode.value.id}/power`, { action })
    ElMessage.success(`电源操作成功: ${response.data.power_status}`)
  } catch (e) {
    ElMessage.error('电源操作失败')
  }
}

// ── 网络检查 ──────────────────────────────────────────────────
const checkNetwork = async (node) => {
  selectedNode.value = node
  try {
    const response = await axios.post(`/api/network/check/${node.id}`)
    networkCheckResult.value = response.data
    networkDialogVisible.value = true
  } catch (e) {
    ElMessage.error('网络检查失败')
  }
}

onMounted(() => {
  loadNodes()
})
</script>

<style scoped>
.nodes-view {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.debug-panel { font-size: 13px; }
.debug-paths { padding: 8px 12px; background: #0d1b2e; border-radius: 4px; margin-bottom: 12px; line-height: 1.8; }
.debug-paths code { color: #79c0ff; font-size: 12px; }
.debug-err { color: #ff7b7b; margin-top: 8px; font-size: 12px; }
.debug-hint { margin-top: 12px; padding: 10px 14px; background: #2a1f0a; border-left: 3px solid #e0a64b; border-radius: 4px; }
.debug-hint ul { margin: 6px 0 0 0; padding-left: 22px; color: #d0d0d0; }
.debug-hint li { margin: 4px 0; }

.header-actions {
  display: flex;
  gap: 10px;
}

.plane-info {
  display: flex;
  align-items: center;
  gap: 8px;
}

.plane-info .ip {
  color: #fff;
  font-size: 13px;
}

.sub-info {
  color: #a0a0a0;
  font-size: 12px;
  margin-top: 4px;
}

.role-text {
  color: #a0a0a0;
  font-size: 11px;
  margin-top: 3px;
}

.power-controls {
  text-align: center;
}

.power-controls p {
  color: #fff;
  margin: 10px 0;
}

.power-buttons {
  display: flex;
  gap: 10px;
  justify-content: center;
  margin-top: 20px;
}

.network-result {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.plane-check {
  padding: 15px;
  background: #0f3460;
  border-radius: 8px;
}

.plane-check h4 {
  color: #e94560;
  margin: 0 0 10px 0;
}

.plane-check p {
  color: #fff;
  margin: 5px 0;
}

/* ── 暗色表格 ── */
.nodes-view :deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: #0d1b2e;
  --el-table-row-hover-bg-color: #1e3a5f;
  --el-table-current-row-bg-color: #1e3a5f;
  --el-table-border-color: #1e293b;
  --el-table-text-color: #cbd5e1;
  --el-table-header-text-color: #64748b;
  --el-fill-color-light: rgba(255, 255, 255, 0.025);
  background-color: transparent;
}
.nodes-view :deep(.el-table th.el-table__cell) {
  background-color: #0d1b2e !important;
  color: #64748b;
  border-bottom-color: #1e293b;
}
.nodes-view :deep(.el-table td.el-table__cell) {
  background-color: transparent !important;
  border-bottom-color: #1e293b;
  color: #cbd5e1;
}
.nodes-view :deep(.el-table tr) {
  background-color: transparent !important;
}
.nodes-view :deep(.el-table__body tr:hover > td.el-table__cell) {
  background-color: #1e3a5f !important;
}
.nodes-view :deep(.el-table--striped .el-table__body tr.el-table__row--striped td.el-table__cell) {
  background-color: rgba(255, 255, 255, 0.025) !important;
}
.nodes-view :deep(.el-table__inner-wrapper::before),
.nodes-view :deep(.el-table__border-left-patch) {
  background-color: #1e293b;
}
.nodes-view :deep(.el-table__empty-block) {
  background-color: transparent;
}

/* ── 编辑对话框 el-divider 暗色 ── */
.nodes-view :deep(.el-dialog .el-divider) {
  border-top-color: #1e293b;
}
.nodes-view :deep(.el-dialog .el-divider__text) {
  background-color: #1a2744;
  color: #64748b;
  font-size: 12px;
  font-weight: 600;
}

.mt-name {
  font-size: 12px;
  color: #d0d0d0;
}

/* ── 节点模板 ── */
.tpl-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}

.tpl-desc {
  color: #909399;
  font-size: 13px;
  flex: 1;
}

.tpl-alert {
  margin-bottom: 10px;
}

.tpl-total {
  color: #909399;
  font-size: 13px;
  margin-right: auto;
}

.tpl-spec {
  color: #909399;
  font-size: 12px;
}

.tpl-meta {
  margin-bottom: 12px;
}

.tpl-addrole {
  margin-top: 10px;
}
</style>

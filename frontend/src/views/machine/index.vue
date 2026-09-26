<template>
  <section class="page" data-module="machine">
    <header class="page-head">
      <div>
        <h2>养护机械管理</h2>
        <p class="page-desc">年检口径：年检日期距今天不足所属班组阈值（默认 30 天）自动标为待年检；维修中、已停用、已报废不参与判定。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="openCreate">登记养护机械</button>
        <button class="btn" type="button" @click="registerInspection()">登记年检</button>
        <button class="btn" type="button" @click="reinspectAll">按新口径重标</button>
        <button class="btn" type="button" @click="exportRows">导出养护机械清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :placeholder="`按${field}检索`" />
      </label>
      <label class="filter-item">
        <span>年检结论</span>
        <select v-model="inspectionFilter">
          <option value="">全部</option>
          <option v-for="item in inspectionOptions" :key="item" :value="item">{{ item }}</option>
        </select>
      </label>
      <button class="btn" type="submit">查询</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in columns" :key="column">{{ column }}</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)">
          <td v-for="column in columns" :key="column">
            <template v-if="column === '机械编号'">
              <span :class="numberClass(row)">{{ row[column] }}</span>
            </template>
            <template v-else-if="column === '年检日期'">
              {{ row[column] ?? '—' }}
              <div v-if="row['剩余天数'] !== null && row['剩余天数'] !== undefined" class="hint">
                剩 {{ row['剩余天数'] }} 天（阈值 {{ row['到期阈值'] }} 天）
              </div>
            </template>
            <template v-else-if="column === '年检结论'">
              <span class="badge" :class="badgeClass(row['年检状态'])">{{ row[column] }}</span>
            </template>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
            <button class="link" type="button" @click="showDetail(row)">详情</button>
            <button class="link" type="button" @click="openEdit(row)">编辑</button>
            <button
              v-for="action in actions"
              :key="action"
              class="link"
              type="button"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="columns.length + 1" class="empty-state">暂无养护机械数据，可先登记养护机械</td>
        </tr>
      </tbody>
    </table>

    <footer class="page-foot">
      <span>共 {{ total }} 条养护机械记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>

    <!-- 详情：结论与台账取自同一后端口径 -->
    <div v-if="detailRow" class="modal-mask" @click.self="detailRow = null">
      <div class="modal">
        <div class="modal-head">
          <h3 class="modal-title">机械详情 · {{ detailRow['机械编号'] }}</h3>
          <button class="modal-close" type="button" @click="detailRow = null">×</button>
        </div>
        <dl class="detail-grid">
          <template v-for="field in detailFields" :key="field">
            <dt>{{ field }}</dt>
            <dd>{{ detailRow[field] ?? '—' }}</dd>
          </template>
          <dt>年检结论</dt>
          <dd>
            <span class="badge" :class="badgeClass(detailRow['年检状态'])">{{ detailRow['年检结论'] }}</span>
            <span v-if="detailRow['剩余天数'] !== null && detailRow['剩余天数'] !== undefined" class="hint">
              （剩余 {{ detailRow['剩余天数'] }} 天，所属班组阈值 {{ detailRow['到期阈值'] }} 天）
            </span>
          </dd>
        </dl>
        <div class="modal-foot">
          <button class="btn" type="button" @click="detailRow = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 登记 / 编辑 -->
    <div v-if="formMode" class="modal-mask" @click.self="closeForm()">
      <div class="modal">
        <div class="modal-head">
          <h3 class="modal-title">{{ formMode === 'create' ? '登记养护机械' : formMode === 'inspection' ? '登记年检' : '编辑养护机械' }}</h3>
          <button class="modal-close" type="button" @click="closeForm()">×</button>
        </div>
        <div class="form-grid">
          <label v-if="formMode === 'inspection'" class="form-item full">
            <span>机械编号 *</span>
            <input v-model="formValues['机械编号']" placeholder="如 MACH-0002" />
          </label>
          <template v-if="formMode !== 'inspection'">
            <label v-for="field in editableFields" :key="field" :class="['form-item', fullWidthFields.includes(field) ? 'full' : '']">
              <span>{{ field }}{{ requiredFields.includes(field) ? ' *' : '' }}</span>
              <input v-model="formValues[field]" :placeholder="`请输入${field}`" />
            </label>
          </template>
          <label v-if="formMode === 'inspection'" class="form-item full">
            <span>年检日期 *（YYYY-MM-DD）</span>
            <input v-model="formValues['年检日期']" placeholder="如 2026-10-06" />
          </label>
          <label v-if="formMode === 'inspection'" class="form-item full">
            <span>检验机构</span>
            <input v-model="formValues['检验机构']" />
          </label>
        </div>
        <p v-if="formHint" class="hint">{{ formHint }}</p>
        <div class="modal-foot">
          <button class="btn" type="button" @click="closeForm()">取消</button>
          <button class="btn primary" type="button" @click="submitForm">保存</button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/machine'
const columns = ["机械编号", "机械名称", "规格型号", "所属班组", "购置日期", "年检日期", "操作人员", "机械状态", "年检结论"]
const actions = ["调度出勤", "维修登记", "停用登记", "申请报废"]
const statuses = ["可用", "出勤中", "维修中", "已停用", "已报废"]
const inspectionOptions = ["正常", "待年检", "已过期", "免检"]
const requiredFields = ["机械编号", "机械名称", "规格型号"]
const editableFields = ["机械编号", "机械名称", "规格型号", "所属班组", "购置日期", "年检日期", "操作人员", "机械状态"]
const fullWidthFields = ["机械名称", "机械状态"]
const detailFields = ["机械编号", "机械名称", "规格型号", "所属班组", "购置日期", "年检日期", "操作人员", "机械状态"]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = columns.slice(0, 3)
const inspectionFilter = ref('')

const detailRow = ref<Row | null>(null)
type FormMode = '' | 'create' | 'edit' | 'inspection'
const formMode = ref<FormMode>('')
// 显式置空，避免把 DOM 事件参数误传进来
const closeForm = () => { formMode.value = '' }
const formValues = ref<Record<string, string>>({})
const editingId = ref<number | null>(null)
const formHint = ref('')

const stats = computed(() => [
  { label: "机械总数", value: total.value },
  { label: "待年检", value: countByVerdict('待年检') },
  { label: "已过期", value: countByVerdict('已过期') },
  { label: "维修/停用", value: rows.value.filter((row) => ['维修中', '已停用', '已报废'].includes(String(row.status))).length },
])

function countByVerdict(verdict: string) {
  return rows.value.filter((row) => row['年检状态'] === verdict).length
}

function badgeClass(verdict: unknown) {
  if (verdict === '正常') return 'ok'
  if (verdict === '待年检') return 'warn'
  if (verdict === '已过期') return 'danger'
  return 'muted'
}

function numberClass(row: Row) {
  if (row['年检状态'] === '已过期') return 'machine-no-danger'
  if (row['年检状态'] === '待年检') return 'machine-no-warn'
  return ''
}

function resetFilters() {
  filters.value = {}
  inspectionFilter.value = ''
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

function openCreate() {
  editingId.value = null
  formValues.value = {}
  formHint.value = '购置日期晚于年检日期、年检已过期且仍在用的数据不允许保存。'
  formMode.value = 'create'
}

function registerInspection(row?: Row) {
  editingId.value = null
  formValues.value = row ? { '机械编号': String(row['机械编号'] ?? '') } : {}
  formHint.value = '同一机械编号多次登记时，以年检日期最近一次为准；年检日期不得早于购置日期。'
  formMode.value = 'inspection'
}

function openEdit(row: Row) {
  editingId.value = Number(row.id)
  formValues.value = Object.fromEntries(
    editableFields.map((field) => [field, row[field] == null ? '' : String(row[field])]),
  )
  formHint.value = '购置日期晚于年检日期、年检已过期且仍为在用状态时无法保存。'
  formMode.value = 'edit'
}

async function showDetail(row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}`)
    if (!response.ok) {
      throw new Error('机械详情读取失败')
    }
    detailRow.value = await response.json()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '机械详情读取失败'
  }
}

async function submitForm() {
  errorMessage.value = ''
  const missing = (formMode.value === 'inspection'
    ? ['机械编号', '年检日期']
    : requiredFields
  ).filter((field) => !formValues.value[field]?.trim())
  if (missing.length) {
    errorMessage.value = `缺少必填字段：${missing.join('、')}`
    return
  }
  const url = formMode.value === 'edit'
    ? `${ENDPOINT}/${editingId.value}`
    : formMode.value === 'inspection'
      ? `${ENDPOINT}/inspection-records`
      : ENDPOINT
  const method = formMode.value === 'edit' ? 'PUT' : 'POST'
  try {
    const response = await request(url, {
      method,
      body: JSON.stringify({ values: formValues.value }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.detail || payload.message || '保存未生效，请核对填写内容')
    }
    formMode.value = ''
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '保存失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ action }),
    })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '养护机械动作未生效，请稍后重试')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护机械操作失败'
  }
}

async function reinspectAll() {
  errorMessage.value = ''
  try {
    const response = await request(`${ENDPOINT}/reinspect`, { method: 'POST' })
    const payload = await response.json()
    if (!response.ok || payload.ok === false) {
      throw new Error(payload.message || '重标失败')
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '重标失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams({
    ...filters.value,
    ...(inspectionFilter.value ? { inspection: inspectionFilter.value } : {}),
  }).toString()
  try {
    const response = await request(`${ENDPOINT}?${query}`)
    if (!response.ok) {
      throw new Error('养护机械列表读取失败')
    }
    const payload = await response.json()
    rows.value = payload.items ?? []
    total.value = payload.total ?? rows.value.length
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护机械列表读取失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.hint { color: var(--muted); font-size: 12px; margin-top: 2px; }
.page-actions { display: flex; gap: 8px; }
</style>

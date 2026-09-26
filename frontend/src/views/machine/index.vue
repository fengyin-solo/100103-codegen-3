<template>
  <section class="page" data-module="machine">
    <header class="page-head">
      <div>
        <h2>养护机械管理</h2>
        <p class="page-desc">维护养护机械，围绕机械编号、机械名称、规格型号、所属班组做登记、筛选与状态流转；年检到期按所属班组阈值自动判定。</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" type="button" @click="toggleCreate">登记养护机械</button>
        <button class="btn" type="button" @click="exportRows">导出养护机械清单</button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <form v-if="showCreate" class="create-bar" @submit.prevent="submitCreate">
      <label v-for="field in createFields" :key="field.key" class="filter-item">
        <span>{{ field.label }}</span>
        <select v-if="field.key === '所属班组'" v-model="createForm[field.key]">
          <option v-for="team in teams" :key="team" :value="team">{{ team }}</option>
        </select>
        <input v-else-if="field.type === 'date'" v-model="createForm[field.key]" type="date" />
        <input v-else v-model="createForm[field.key]" :placeholder="`请输入${field.label}`" />
      </label>
      <button class="btn primary" type="submit">保存</button>
      <button class="btn ghost" type="button" @click="toggleCreate">取消</button>
    </form>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>机械编号</span>
        <input v-model="filters.keyword" placeholder="按机械编号检索" />
      </label>
      <label class="filter-item">
        <span>机械状态</span>
        <select v-model="filters.status">
          <option value="">全部状态</option>
          <option v-for="status in statuses" :key="status" :value="status">{{ status }}</option>
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
            <span
              v-if="column === '年检结论'"
              class="tag"
              :class="tagClass(row[column])"
              :title="String(row['年检提示'] ?? '')"
            >
              {{ row[column] ?? '—' }}
            </span>
            <template v-else>{{ row[column] ?? '—' }}</template>
          </td>
          <td class="row-actions">
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
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

import { request } from '@/api/client'

type Row = Record<string, string | number | null>

const ENDPOINT = '/api/machine'
const columns = ["机械编号", "机械名称", "规格型号", "所属班组", "购置日期", "年检日期", "剩余天数", "年检结论", "操作人员", "机械状态"]
const actions = ["调度出勤", "维修登记", "登记年检", "申请报废"]
const statuses = ["可用", "出勤中", "维修中", "已报废"]
const teams = ["机械一班", "机械二班", "桥梁机械班"]
const createFields = [
  { key: '机械编号', label: '机械编号' },
  { key: '机械名称', label: '机械名称' },
  { key: '规格型号', label: '规格型号' },
  { key: '所属班组', label: '所属班组' },
  { key: '购置日期', label: '购置日期', type: 'date' },
  { key: '年检日期', label: '年检日期', type: 'date' },
  { key: '操作人员', label: '操作人员' },
]

const rows = ref<Row[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const showCreate = ref(false)
const createForm = ref<Record<string, string>>({ '所属班组': teams[0] })

const stats = computed(() => [
  { label: '可用机械', value: rows.value.filter((row) => row.status === '可用').length },
  { label: '出勤机械', value: rows.value.filter((row) => row.status === '出勤中').length },
  { label: '待年检', value: rows.value.filter((row) => row['年检结论'] === '待年检').length },
  { label: '已过期', value: rows.value.filter((row) => row['年检结论'] === '已过期').length },
])

function tagClass(conclusion: unknown): string {
  switch (conclusion) {
    case '待年检':
      return 'due'
    case '已过期':
      return 'expired'
    case '正常':
      return 'ok'
    default:
      return 'muted'
  }
}

function readError(payload: unknown, fallback: string): string {
  const data = payload as { message?: unknown; detail?: unknown } | null
  if (data && typeof data.message === 'string') return data.message
  if (data && typeof data.detail === 'string') return data.detail
  return fallback
}

function toggleCreate() {
  showCreate.value = !showCreate.value
  errorMessage.value = ''
}

function resetFilters() {
  filters.value = {}
  void reload()
}

function exportRows() {
  window.open(`${ENDPOINT}/export`, '_blank')
}

async function submitCreate() {
  errorMessage.value = ''
  try {
    const response = await request(ENDPOINT, {
      method: 'POST',
      body: JSON.stringify({ values: { ...createForm.value } }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(readError(payload, '养护机械登记失败'))
    }
    showCreate.value = false
    createForm.value = { '所属班组': teams[0] }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护机械登记失败'
  }
}

async function runAction(action: string, row: Row) {
  errorMessage.value = ''
  const values: Record<string, string> = { action }
  if (action === '登记年检') {
    const due = window.prompt(`请输入机械 ${row['机械编号']} 的新年检日期（YYYY-MM-DD）`)
    if (!due) {
      return
    }
    values['年检日期'] = due
  }
  try {
    const response = await request(`${ENDPOINT}/${row.id}/actions`, {
      method: 'POST',
      body: JSON.stringify({ values }),
    })
    const payload = await response.json()
    if (!response.ok || !payload.ok) {
      throw new Error(readError(payload, '养护机械动作未生效，请稍后重试'))
    }
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '养护机械操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  const query = new URLSearchParams()
  if (filters.value.keyword) {
    query.set('keyword', filters.value.keyword)
  }
  if (filters.value.status) {
    query.set('status', filters.value.status)
  }
  try {
    const response = await request(`${ENDPOINT}?${query.toString()}`)
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

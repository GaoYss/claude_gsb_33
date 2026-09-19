<template>
  <el-dialog :model-value="visible" title="批量补价 · 单价待补记录"
             width="860px" top="6vh" destroy-on-close @update:model-value="close">
    <el-alert type="warning" :closable="false" show-icon
              title="补价后金额 = 数量 × 单价，提交即刻计入各处统计；同一批次重复提交只会生效一次。" />

    <div class="toolbar">
      <span class="summary-text">
        待补价 <strong>{{ rows.length }}</strong> 条
        <template v-if="remaining > 0">（另有 {{ remaining }} 条，提交本批后可再次打开继续）</template>
        ，本批金额合计 <strong>{{ formatCurrency(totalAmount) }}</strong>
      </span>
      <el-button :icon="'Refresh'" text :loading="loading" @click="loadPending">刷新</el-button>
    </div>

    <el-table :data="rows" v-loading="loading" border stripe max-height="420">
      <el-table-column prop="replacement_no" label="编号" width="140" />
      <el-table-column label="所属绿地" min-width="130" show-overflow-tooltip>
        <template #default="{ row }">{{ row.green_space?.name || '-' }}</template>
      </el-table-column>
      <el-table-column label="植株" min-width="120">
        <template #default="{ row }">
          <div>{{ row.plant_name }}</div>
          <EnumTag group="plant_category" :value="row.plant_category" :label="row.plant_category_label" />
        </template>
      </el-table-column>
      <el-table-column label="数量" width="100" align="right">
        <template #default="{ row }">{{ formatNumber(row.quantity) }} {{ row.unit_label }}</template>
      </el-table-column>
      <el-table-column prop="replace_date" label="更换日期" width="105" />
      <el-table-column label="单价（元）" width="170">
        <template #default="{ row }">
          <el-input-number v-model="row.unit_price" :min="0" :max="99999999" :precision="2"
                           :controls="false" placeholder="必填" style="width: 100%" />
        </template>
      </el-table-column>
      <el-table-column label="金额（元）" width="120" align="right">
        <template #default="{ row }">
          <span v-if="hasPrice(row)">{{ formatCurrency(row.quantity * row.unit_price) }}</span>
          <span v-else class="amount-missing">待补价</span>
        </template>
      </el-table-column>
      <template #empty>没有单价待补的更换记录</template>
    </el-table>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" :disabled="!rows.length" @click="submit">
        提交补价（{{ rows.length }} 条）
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'

import { plantReplacementApi } from '@/api'
import EnumTag from '@/components/common/EnumTag.vue'
import { formatCurrency, formatNumber } from '@/utils/format'

const emit = defineEmits(['saved'])

const visible = ref(false)
const loading = ref(false)
const submitting = ref(false)
const rows = ref([])
const remaining = ref(0)
// 批次号在打开弹窗时生成一次：提交失败重试仍用同一批次号，服务端据此幂等去重
const batchNo = ref('')

const totalAmount = computed(() =>
  rows.value.reduce((sum, row) => (hasPrice(row) ? sum + row.quantity * row.unit_price : sum), 0),
)

function hasPrice(row) {
  return row.unit_price !== null && row.unit_price !== undefined && row.unit_price !== ''
}

function newBatchNo() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID()
  return `PF-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`
}

async function loadPending() {
  loading.value = true
  try {
    const data = await plantReplacementApi.list({ price_pending: true, page: 1, page_size: 100 })
    rows.value = (data.items || []).map((item) => ({ ...item, unit_price: null }))
    remaining.value = Math.max(0, (data.meta?.total || 0) - rows.value.length)
  } finally {
    loading.value = false
  }
}

function open() {
  batchNo.value = newBatchNo()
  visible.value = true
  loadPending()
}

function close() {
  visible.value = false
}

async function submit() {
  const missing = rows.value.filter((row) => !hasPrice(row))
  if (missing.length) {
    ElMessage.warning(`还有 ${missing.length} 条未填写单价，请补齐后再提交`)
    return
  }
  submitting.value = true
  try {
    const result = await plantReplacementApi.priceFill({
      batch_no: batchNo.value,
      items: rows.value.map((row) => ({ id: row.id, unit_price: row.unit_price })),
    })
    const skippedTip = result.skipped_count
      ? `，${result.skipped_count} 条此前已补过、自动跳过`
      : ''
    ElMessage.success(
      `补价完成：${result.applied_count} 条生效，金额合计 ${formatCurrency(result.amount_total)}${skippedTip}`,
    )
    emit('saved')
    if (remaining.value > 0) {
      // 还有未装入本批的待补记录：换新批次号继续补
      batchNo.value = newBatchNo()
      await loadPending()
    } else {
      close()
    }
  } catch (error) {
    // 422 的字段错误拦截器不弹窗，这里统一提示；批次冲突（409）由拦截器提示
    if (error?.status === 422) {
      const detail = Object.values(error.details || {})[0]
      ElMessage.error(detail ? `${error.message}：${detail}` : error.message)
    }
  } finally {
    submitting.value = false
  }
}

defineExpose({ open })
</script>

<style scoped>
.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin: 12px 0;
}

.summary-text {
  color: #606266;
  font-size: 13px;
}

.amount-missing {
  color: #e6a23c;
}
</style>

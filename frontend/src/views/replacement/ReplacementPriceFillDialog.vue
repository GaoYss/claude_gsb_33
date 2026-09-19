<template>
  <el-dialog :model-value="visible" title="批量补录单价" width="760px" top="6vh"
             destroy-on-close @update:model-value="close">
    <el-alert type="info" show-icon :closable="false"
              title="补价后金额按「数量 × 单价」重算，并同步更新类别/原因汇总、总览累计投入与绿地档案；已补价的记录重复提交不会重复生效。" />
    <el-table :data="rows" border size="small" style="margin-top: 12px" max-height="420">
      <el-table-column prop="replacement_no" label="编号" width="150" />
      <el-table-column label="植株名称" min-width="130" show-overflow-tooltip>
        <template #default="{ row }">{{ row.plant_name }}</template>
      </el-table-column>
      <el-table-column label="数量" width="110" align="right">
        <template #default="{ row }">{{ formatNumber(row.quantity) }} {{ row.unit_label }}</template>
      </el-table-column>
      <el-table-column label="单价（元）" width="200">
        <template #default="{ row, $index }">
          <el-input-number v-model="row._price" :min="0" :max="99999999" :precision="2"
                           :controls="false" placeholder="请输入单价" style="width: 100%" />
          <div v-if="rowErrors[$index]" class="row-error">{{ rowErrors[$index] }}</div>
        </template>
      </el-table-column>
      <el-table-column label="金额（元）" width="120" align="right">
        <template #default="{ row }">{{ previewAmount(row) }}</template>
      </el-table-column>
    </el-table>
    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确认补价</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

import { plantReplacementApi } from '@/api'
import { formatCurrency, formatNumber } from '@/utils/format'

const emit = defineEmits(['saved'])

const visible = ref(false)
const submitting = ref(false)
const rows = ref([])
const rowErrors = ref({})

function open(pendingRows = []) {
  rows.value = pendingRows.map((row) => ({ ...row, _price: null }))
  rowErrors.value = {}
  visible.value = true
}

function close() {
  visible.value = false
}

function previewAmount(row) {
  if (row._price === null || row._price === undefined || row._price === '') return '-'
  const amount = Number(row.quantity || 0) * Number(row._price || 0)
  return formatCurrency(Number.isFinite(amount) ? amount : 0)
}

async function submit() {
  const errors = {}
  rows.value.forEach((row, index) => {
    const price = Number(row._price)
    if (row._price === null || row._price === undefined || row._price === '' || !Number.isFinite(price)) {
      errors[index] = '请填写单价'
    } else if (price < 0) {
      errors[index] = '单价不能小于 0'
    }
  })
  rowErrors.value = errors
  if (Object.keys(errors).length) return

  submitting.value = true
  try {
    const items = rows.value.map((row) => ({ id: row.id, unit_price: Number(row._price) }))
    const result = await plantReplacementApi.fillPrices(items)
    const message = `补价完成：本次生效 ${result.filled_count} 条` +
      `（新增金额 ${formatCurrency(result.filled_amount)}），跳过 ${result.skipped_count} 条`
    if (result.skipped_count > 0) {
      ElMessage.warning(message)
    } else {
      ElMessage.success(message)
    }
    emit('saved')
    close()
  } catch {
    // 错误提示由请求拦截器统一弹出
  } finally {
    submitting.value = false
  }
}

defineExpose({ open })
</script>

<style scoped>
.row-error {
  color: #f56c6c;
  font-size: 12px;
  line-height: 1.4;
}
</style>

import { createResourceApi } from './client'
import http from './client'

export const plantReplacementApi = {
  ...createResourceApi('plant-replacements'),
  summary: (params) => http.get('/plant-replacements/summary', { params }),
  // 批量补录单价：items 为 [{ id, unit_price }]，重复提交只生效一次
  fillPrices: (items) => http.post('/plant-replacements/price-fill', { items }),
}

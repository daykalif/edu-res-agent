import request from '@/utils/request'

/**
 * AI对话请求
 */
export function chatApi(data) {
  return request({
    url: '/api/ai/chat',
    method: 'post',
    data,
    timeout: 60000 // 设置超时时间为60秒
  })
}

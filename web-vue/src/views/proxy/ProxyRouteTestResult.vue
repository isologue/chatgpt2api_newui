<template>
  <p v-if="result" class="mt-1.5 break-all text-[11px]" :class="result.ok ? 'text-emerald-600' : 'text-rose-600'">
    <template v-if="result.ok">
      {{ result.error || `测试成功${result.status ? `：HTTP ${result.status}` : ''}${result.latency_ms ? `，${result.latency_ms}ms` : ''}` }}
    </template>
    <template v-else>
      {{ result.error || '测试失败' }}
    </template>
  </p>
</template>

<script setup lang="ts">
import type { ProxyTestResult } from '@/api/proxy'

defineProps<{
  result?: ProxyTestResult | null
}>()
</script>
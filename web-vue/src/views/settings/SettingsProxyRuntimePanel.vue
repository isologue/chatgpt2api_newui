<template>
  <FormSection title="出站路由">
    <div v-if="egressMode === 'direct'" class="rounded-xl border border-border bg-background px-3 py-3 text-xs">
      <p class="font-semibold text-foreground">直连</p>
      <p class="mt-1 leading-5 text-muted-foreground">
        默认不使用代理。账号自身配置的独立代理仍按账号路由规则生效；本页不再额外配置 A/B 出口。
      </p>
    </div>
    <div v-else-if="egressMode === 'single_proxy'" class="grid gap-3 md:grid-cols-2">
      <div class="rounded-xl border border-sky-500/25 bg-sky-500/5 px-3 py-3 text-xs">
        <p class="font-semibold text-foreground">主代理</p>
        <p class="mt-1 leading-5 text-muted-foreground">账号鉴权、会话、SSE、图片上传和下载都走主代理。</p>
      </div>
      <div class="rounded-xl border border-amber-500/25 bg-amber-500/5 px-3 py-3 text-xs">
        <p class="font-semibold text-foreground">备用代理</p>
        <p class="mt-1 leading-5 text-muted-foreground">主代理触发连接故障或生图出口熔断时，按原有逻辑切换一次。</p>
      </div>
    </div>
    <div v-else class="grid gap-3 md:grid-cols-2">
      <div class="rounded-xl border border-sky-500/25 bg-sky-500/5 px-3 py-3 text-xs">
        <p class="font-semibold text-foreground">控制出口 B · 稳定优先</p>
        <p class="mt-1 leading-5 text-muted-foreground">账号鉴权、会话、chat-requirements、生图 SSE、上传元数据和结果轮询走 B。</p>
      </div>
      <div class="rounded-xl border border-amber-500/25 bg-amber-500/5 px-3 py-3 text-xs">
        <p class="font-semibold text-foreground">资源出口 A · 流量成本优先</p>
        <p class="mt-1 leading-5 text-muted-foreground">参考图大文件上传和最终图片下载走 A；可单独设置 A 的备用出口。</p>
      </div>
    </div>

    <div class="rounded-xl border border-border bg-background px-3 py-3">
      <div class="grid grid-cols-2 gap-2 text-xs md:grid-cols-4 xl:grid-cols-6">
        <div v-for="item in summaryItems" :key="item.label" class="min-w-0 rounded-lg border border-border/70 bg-card px-2.5 py-2">
          <p class="text-muted-foreground">{{ item.label }}</p>
          <p class="mt-1 truncate font-medium text-foreground" :title="item.value">{{ item.value }}</p>
        </div>
      </div>
    </div>

    <div class="grid gap-3 lg:grid-cols-2">
      <div v-for="card in routeMetricCards" :key="card.key" class="rounded-xl border border-border bg-background px-3 py-3 text-xs">
        <div class="flex items-start justify-between gap-3">
          <div>
            <p class="font-semibold text-foreground">{{ card.title }}</p>
            <p class="mt-1 text-muted-foreground">实际出口：{{ card.metric.last_egress_label || card.egressLabel || '-' }}</p>
          </div>
          <span class="rounded-full border border-border px-2 py-0.5 text-[11px] text-muted-foreground">inflight {{ card.metric.inflight || 0 }}</span>
        </div>
        <div class="mt-3 grid grid-cols-3 gap-2 sm:grid-cols-6">
          <div><p class="text-muted-foreground">总请求</p><p class="mt-1 font-medium">{{ card.metric.total || 0 }}</p></div>
          <div><p class="text-muted-foreground">成功</p><p class="mt-1 font-medium text-emerald-600">{{ card.metric.success || 0 }}</p></div>
          <div><p class="text-muted-foreground">失败</p><p class="mt-1 font-medium text-rose-600">{{ card.metric.failed || 0 }}</p></div>
          <div><p class="text-muted-foreground">回退</p><p class="mt-1 font-medium">{{ card.metric.fallback || 0 }}</p></div>
          <div><p class="text-muted-foreground">平均</p><p class="mt-1 font-medium">{{ card.metric.avg_ms || 0 }}ms</p></div>
          <div><p class="text-muted-foreground">峰值</p><p class="mt-1 font-medium">{{ card.metric.max_ms || 0 }}ms</p></div>
        </div>
        <p v-if="card.metric.last_error" class="mt-2 break-all text-rose-600">最近错误：{{ card.metric.last_error }}</p>
      </div>
    </div>

    <div class="settings-check-grid">
      <div class="settings-check-item"><div class="settings-check-control"><Checkbox v-model="proxyRuntime.skip_ssl_verify">跳过上游 SSL 校验</Checkbox><HelpTip text="仅在代理或上游证书链异常时使用。" /></div></div>
    </div>

    <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <FormField label="出站方式">
        <GroupedSelectMenu
          :model-value="egressMode"
          :options="proxyRuntimeEgressOptions"
          selected-indicator="none"
          aria-label="代理出站方式"
          block
          @update:model-value="setEgressMode"
        />
      </FormField>

      <template v-if="egressMode === 'single_proxy'">
        <ProxyReferenceField
          v-model="proxyRuntime.control_proxy_url"
          label="主代理"
          :groups="groups"
          help="所有控制请求和图片资源请求都走主代理。支持直接填写代理地址或选择代理组。"
          :testing="routeTestingKey === 'control'"
          :result="routeTestResults.control"
          test-label="测试主代理"
          @change="clearRouteResult('control')"
          @test="$emit('testProxyRoute', 'control')"
        />
        <ProxyReferenceField
          v-model="proxyRuntime.control_fallback_proxy_url"
          label="备用代理"
          :groups="groups"
          help="主代理连接失败、生图出口触发熔断时使用；留空表示不配置独立备用。"
          allow-off
          allow-direct
          :testing="routeTestingKey === 'control_fallback'"
          :result="routeTestResults.control_fallback"
          test-label="测试备用"
          @change="clearRouteResult('control_fallback')"
          @test="$emit('testProxyRoute', 'control_fallback')"
        />
      </template>

      <template v-else-if="egressMode === 'split_proxy'">
        <ProxyReferenceField
          v-model="proxyRuntime.control_proxy_url"
          label="控制出口 B"
          :groups="groups"
          help="账号鉴权、会话、SSE 和生图控制请求使用。支持直接填写代理地址或选择代理组。"
          :testing="routeTestingKey === 'control'"
          :result="routeTestResults.control"
          test-label="测试 B"
          @change="clearRouteResult('control')"
          @test="$emit('testProxyRoute', 'control')"
        />
        <ProxyReferenceField
          v-model="proxyRuntime.control_fallback_proxy_url"
          label="控制备用出口"
          :groups="groups"
          help="控制出口发生连接故障或触发熔断时使用；留空则不设置独立备用。"
          allow-off
          allow-direct
          :testing="routeTestingKey === 'control_fallback'"
          :result="routeTestResults.control_fallback"
          test-label="测试备用"
          @change="clearRouteResult('control_fallback')"
          @test="$emit('testProxyRoute', 'control_fallback')"
        />
        <ProxyReferenceField
          v-model="proxyRuntime.resource_proxy_url"
          label="资源出口 A"
          :groups="groups"
          help="图片大文件上传和最终图片下载使用。支持直接填写代理地址或选择代理组。"
          :testing="routeTestingKey === 'resource'"
          :result="routeTestResults.resource"
          test-label="测试 A"
          @change="clearRouteResult('resource')"
          @test="$emit('testProxyRoute', 'resource')"
        />
        <ProxyReferenceField
          v-model="proxyRuntime.resource_fallback_proxy_url"
          label="资源备用出口"
          :groups="groups"
          help="A 上传或下载失败时重试一次；留空时自动回退到控制出口 B。"
          allow-off
          allow-direct
          :testing="routeTestingKey === 'resource_fallback'"
          :result="routeTestResults.resource_fallback"
          test-label="测试备用"
          @change="clearRouteResult('resource_fallback')"
          @test="$emit('testProxyRoute', 'resource_fallback')"
        />
      </template>
    </div>
  </FormSection>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Checkbox, FormField, FormSection, HelpTip } from 'nanocat-ui'
import type { ProxyGroup, ProxyTestResult } from '@/api/proxy'
import type { ProxyRouteMetric, ProxyRuntimeStatus, Settings } from '@/types/api'
import GroupedSelectMenu from '@/components/ui/GroupedSelectMenu.vue'
import ProxyReferenceField from '@/views/proxy/ProxyReferenceField.vue'
import { buildProxyRuntimeSummaryItems, proxyRuntimeEgressOptions } from '@/views/settings/settingsView'

type ProxyRouteKey = 'control' | 'resource' | 'control_fallback' | 'resource_fallback'

const props = defineProps<{
  settings: Settings
  groups: ProxyGroup[]
  runtimeStatus: ProxyRuntimeStatus | null
  routeTestingKey: string
  routeTestResults: Partial<Record<ProxyRouteKey, ProxyTestResult | null>>
}>()

const emit = defineEmits<{
  testProxyRoute: [key: ProxyRouteKey]
  clearProxyRouteResult: [key: ProxyRouteKey]
}>()

const proxyRuntime = computed(() => props.settings.proxy_runtime)
const egressMode = computed(() => proxyRuntime.value.egress_mode)
const summaryItems = computed(() => buildProxyRuntimeSummaryItems(props.runtimeStatus))
const emptyMetric: ProxyRouteMetric = {}
const routeMetricCards = computed(() => {
  const split = egressMode.value === 'split_proxy'
  return [
    { key: 'control', title: split ? '控制出口 B 监控' : egressMode.value === 'single_proxy' ? '主代理 · 控制请求' : '直连 · 控制请求', egressLabel: props.runtimeStatus?.control_egress_label || '', metric: props.runtimeStatus?.route_metrics?.control || emptyMetric },
    { key: 'resource', title: split ? '资源出口 A 监控' : egressMode.value === 'single_proxy' ? '主代理 · 图片资源' : '直连 · 图片资源', egressLabel: props.runtimeStatus?.resource_egress_label || '', metric: props.runtimeStatus?.route_metrics?.resource || emptyMetric },
  ]
})

function setEgressMode(value: string | string[]) {
  const next = Array.isArray(value) ? value[0] : value
  proxyRuntime.value.egress_mode = next as typeof proxyRuntime.value.egress_mode
  for (const key of ['control', 'resource', 'control_fallback', 'resource_fallback'] as ProxyRouteKey[]) emit('clearProxyRouteResult', key)
}


function clearRouteResult(key: ProxyRouteKey) {
  emit('clearProxyRouteResult', key)
}
</script>

<style scoped>
.settings-check-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(13.5rem, 1fr)); gap: 8px; }
.settings-check-item { min-height: 38px; border: 1px solid hsl(var(--border)); border-radius: 14px; background: hsl(var(--background) / 0.72); transition: border-color 0.16s ease, background-color 0.16s ease; }
.settings-check-item:hover { border-color: hsl(var(--foreground) / 0.18); background: hsl(var(--muted) / 0.24); }
.settings-check-control { display: flex; min-height: 38px; align-items: center; gap: 8px; padding-right: 10px; }
.settings-check-item :deep(label) { display: flex; width: 100%; flex: 1; min-height: 38px; align-items: center; gap: 10px; padding: 9px 11px; }
.settings-check-item :deep(label > span:last-child) { color: hsl(var(--foreground) / 0.78); line-height: 1.35; }
</style>

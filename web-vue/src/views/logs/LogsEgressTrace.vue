<template>
  <section class="egress-trace">
    <button
      type="button"
      class="egress-trace__header"
      :aria-expanded="visible"
      @click="visible = !visible"
    >
      <span class="egress-trace__title">
        <Icon icon="lucide:route" />
        步骤出口追踪
      </span>
      <span class="egress-trace__summary">
        {{ steps.length }} 个步骤
        <Icon
          icon="lucide:chevron-down"
          :class="{ 'egress-trace__chevron--open': visible }"
        />
      </span>
    </button>

    <div v-show="visible" class="egress-trace__list">
      <article v-for="step in steps" :key="step.key" class="egress-trace__item">
        <div class="egress-trace__stage">
          <span class="egress-trace__dot" :class="`egress-trace__dot--${routeTone(step.route)}`" />
          <div>
            <strong>{{ step.stage }}</strong>
            <span v-if="step.slot || step.attempt" class="egress-trace__attempt">
              <template v-if="step.slot">图片 {{ step.slot }}</template>
              <template v-if="step.attempt"> · 尝试 {{ step.attempt }}</template>
            </span>
          </div>
        </div>

        <div class="egress-trace__route">
          <span class="egress-trace__route-label" :class="`egress-trace__route-label--${routeTone(step.route)}`">
            {{ step.routeLabel }}
          </span>
          <template v-if="step.route === 'fallback'">
            <div class="egress-trace__fallback">
              <code>{{ step.fromLabel || step.fromKey || '原出口' }}</code>
              <Icon icon="lucide:arrow-right" />
              <code>{{ step.toLabel || step.toKey || '备用出口' }}</code>
            </div>
          </template>
          <template v-else>
            <strong>{{ step.egressLabel || step.egressKey || proxySourceText(step.proxySource) }}</strong>
            <code v-if="step.egressKey && step.egressKey !== step.egressLabel">{{ step.egressKey }}</code>
          </template>
          <span v-if="step.proxySource" class="egress-trace__source">
            来源：{{ proxySourceText(step.proxySource) }}
          </span>
          <span v-if="step.operation" class="egress-trace__source">
            操作：{{ step.operation }}
          </span>
          <span v-if="step.inherited" class="egress-trace__inherited">
            历史日志未逐步记录，当前为总出口参考
          </span>
          <span v-if="step.reason" class="egress-trace__reason" :title="step.reason">
            原因：{{ step.reason }}
          </span>
        </div>

        <time v-if="step.time" class="egress-trace__time">{{ step.time }}</time>
      </article>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { Icon } from '@iconify/vue'
import type { DetailEgressStep } from '@/views/logs/logDetailView'

defineProps<{
  steps: DetailEgressStep[]
}>()

const visible = ref(true)

function routeTone(route: DetailEgressStep['route']): 'control' | 'resource' | 'fallback' | 'unknown' {
  return route
}

function proxySourceText(value: string): string {
  if (!value || value === 'direct') return '直连'
  if (value.includes('runtime_control')) return '控制代理配置'
  if (value.includes('runtime_resource')) return '资源代理配置'
  if (value.includes('fallback')) return '备用代理配置'
  if (value.includes('account_group')) return '账号组代理'
  if (value.includes('account')) return '账号代理'
  if (value.includes('default') || value.includes('global')) return '默认代理'
  return value
}
</script>

<style scoped>
.egress-trace {
  overflow: hidden;
  border: 1px solid hsl(var(--border));
  border-radius: 8px;
  background: hsl(var(--card));
}

.egress-trace__header {
  display: flex;
  width: 100%;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 14px;
  color: hsl(var(--foreground));
  text-align: left;
}

.egress-trace__title,
.egress-trace__summary {
  display: inline-flex;
  align-items: center;
  gap: 7px;
}

.egress-trace__title {
  font-size: 13px;
  font-weight: 650;
}

.egress-trace__summary {
  font-size: 11px;
  color: hsl(var(--muted-foreground));
}

.egress-trace__summary svg {
  transition: transform 160ms ease;
}

.egress-trace__chevron--open {
  transform: rotate(180deg);
}

.egress-trace__list {
  border-top: 1px solid hsl(var(--border));
}

.egress-trace__item {
  display: grid;
  grid-template-columns: minmax(8rem, 0.65fr) minmax(0, 1.4fr) auto;
  gap: 12px;
  padding: 11px 14px;
}

.egress-trace__item + .egress-trace__item {
  border-top: 1px dashed hsl(var(--border));
}

.egress-trace__stage {
  display: flex;
  min-width: 0;
  align-items: flex-start;
  gap: 8px;
}

.egress-trace__stage strong {
  display: block;
  font-size: 12px;
  font-weight: 650;
  color: hsl(var(--foreground));
}

.egress-trace__attempt,
.egress-trace__time,
.egress-trace__source {
  font-size: 10px;
  color: hsl(var(--muted-foreground));
}

.egress-trace__dot {
  margin-top: 5px;
  width: 7px;
  height: 7px;
  flex: 0 0 auto;
  border-radius: 999px;
  background: hsl(var(--muted-foreground));
}

.egress-trace__dot--control { background: #3b82f6; }
.egress-trace__dot--resource { background: #10b981; }
.egress-trace__dot--fallback { background: #f59e0b; }

.egress-trace__route {
  display: flex;
  min-width: 0;
  flex-wrap: wrap;
  align-items: center;
  gap: 5px 8px;
}

.egress-trace__route > strong {
  overflow-wrap: anywhere;
  font-size: 12px;
  font-weight: 600;
}

.egress-trace__route code,
.egress-trace__fallback code {
  overflow-wrap: anywhere;
  border-radius: 4px;
  background: hsl(var(--muted) / 0.72);
  padding: 2px 5px;
  font-size: 10px;
  color: hsl(var(--muted-foreground));
}

.egress-trace__route-label {
  border-radius: 999px;
  padding: 2px 6px;
  font-size: 10px;
  font-weight: 650;
}

.egress-trace__route-label--control {
  background: rgb(59 130 246 / 0.12);
  color: #2563eb;
}

.egress-trace__route-label--resource {
  background: rgb(16 185 129 / 0.12);
  color: #059669;
}

.egress-trace__route-label--fallback {
  background: rgb(245 158 11 / 0.14);
  color: #d97706;
}

.egress-trace__route-label--unknown {
  background: hsl(var(--muted));
  color: hsl(var(--muted-foreground));
}

.egress-trace__fallback {
  display: inline-flex;
  min-width: 0;
  align-items: center;
  gap: 5px;
}

.egress-trace__inherited {
  width: 100%;
  font-size: 10px;
  color: #d97706;
}

.egress-trace__reason {
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 10px;
  color: hsl(var(--destructive));
}

.egress-trace__time {
  white-space: nowrap;
  text-align: right;
}

@media (max-width: 640px) {
  .egress-trace__item {
    grid-template-columns: 1fr;
    gap: 7px;
  }

  .egress-trace__time {
    text-align: left;
  }
}
</style>

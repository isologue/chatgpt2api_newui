<template>
  <div class="register-task-settings">
    <FormSection title="任务参数" density="roomy">
      <div class="register-form-grid">
        <label class="register-field">
          <span class="register-label">任务模式</span>
          <GroupedSelectMenu
            v-model="config.mode"
            :groups="registerModeGroups"
            selected-indicator="none"
            :disabled="config.enabled"
            block
          />
        </label>

        <label v-if="config.mode === 'total'" class="register-field">
          <span class="register-label">注册总数</span>
          <Input
            v-model.number="config.total"
            type="number"
            min="1"
            block
            :disabled="config.enabled || config.mode !== 'total'"
          />
        </label>

        <label v-else-if="config.mode === 'quota'" class="register-field">
          <span class="register-label">目标剩余额度</span>
          <Input
            v-model.number="config.target_quota"
            type="number"
            min="1"
            block
            :disabled="config.enabled"
          />
        </label>

        <label v-else class="register-field">
          <span class="register-label">目标可用账号</span>
          <Input
            v-model.number="config.target_available"
            type="number"
            min="1"
            block
            :disabled="config.enabled"
          />
        </label>

        <label class="register-field">
          <span class="register-label">线程数</span>
          <Input
            v-model.number="config.threads"
            type="number"
            min="1"
            block
            :disabled="config.enabled"
          />
        </label>

        <label v-if="config.mode !== 'total'" class="register-field">
          <span class="register-label">检查间隔（秒）</span>
          <Input
            v-model.number="config.check_interval"
            type="number"
            min="1"
            block
            :disabled="config.enabled"
          />
        </label>

        <label class="register-field">
          <span class="register-label">注册代理</span>
          <GroupedSelectMenu
            :model-value="proxyMode"
            :groups="registerProxyModeGroups"
            selected-indicator="none"
            :disabled="config.enabled"
            block
            @update:model-value="emit('update-proxy-mode', $event)"
          />
        </label>

        <label v-if="proxyMode === 'group'" class="register-field">
          <span class="register-label">代理组</span>
          <GroupedSelectMenu
            :model-value="selectedProxyGroupId"
            :groups="proxyGroupGroups"
            selected-indicator="none"
            :disabled="config.enabled"
            block
            @update:model-value="emit('select-proxy-group', $event)"
          />
        </label>

        <label v-else-if="proxyMode === 'custom'" class="register-field">
          <span class="register-label">自定义代理</span>
          <Input
            :model-value="customProxyInput"
            block
            root-class="font-mono"
            placeholder="http://127.0.0.1:7890"
            :disabled="config.enabled"
            @update:model-value="emit('update-custom-proxy', $event)"
          />
        </label>

        <p class="register-proxy-hint register-field--full">
          {{ proxyHint }}
        </p>
      </div>
    </FormSection>

    <FormSection title="注册清障" density="roomy">
      <div class="register-form-grid">
        <label class="register-checkbox-field register-field--full">
          <Checkbox v-model="config.clearance.enabled" :disabled="config.enabled">
            启用 Cloudflare 注册清障
          </Checkbox>
          <span class="register-checkbox-hint">只用于注册 auth.openai.com；清障和注册请求固定使用同一个注册代理节点，不参与生图出站分流。</span>
        </label>

        <label class="register-field">
          <span class="register-label">清障方式</span>
          <GroupedSelectMenu
            v-model="config.clearance.mode"
            :groups="clearanceModeGroups"
            selected-indicator="none"
            :disabled="config.enabled || !config.clearance.enabled"
            block
          />
        </label>

        <label v-if="config.clearance.mode === 'flaresolverr'" class="register-field register-field--full">
          <span class="register-label">FlareSolverr URL</span>
          <Input v-model.trim="config.clearance.flaresolverr_url" block root-class="font-mono" placeholder="http://flaresolverr:8191" :disabled="config.enabled || !config.clearance.enabled" />
        </label>

        <template v-if="config.clearance.mode === 'manual'">
          <label class="register-field">
            <span class="register-label">cf_clearance</span>
            <Input v-model.trim="config.clearance.cf_clearance" block root-class="font-mono" :placeholder="config.clearance.has_cf_clearance ? '已保存，留空则沿用' : '手动填写 cf_clearance'" :disabled="config.enabled || !config.clearance.enabled" />
          </label>
          <label class="register-field">
            <span class="register-label">Cookie</span>
            <Input v-model.trim="config.clearance.cf_cookies" block root-class="font-mono" :placeholder="config.clearance.has_cf_cookies ? '已保存，留空则沿用' : '可粘贴完整 Cookie'" :disabled="config.enabled || !config.clearance.enabled" />
          </label>
        </template>

        <label class="register-field register-field--full">
          <span class="register-label">User-Agent</span>
          <Input v-model.trim="config.clearance.user_agent" block root-class="font-mono" placeholder="Mozilla/5.0 ..." :disabled="config.enabled || !config.clearance.enabled" />
        </label>
        <label class="register-field">
          <span class="register-label">清障超时（秒）</span>
          <Input v-model.number="config.clearance.timeout_sec" type="number" min="1" block :disabled="config.enabled || !config.clearance.enabled" />
        </label>
        <label class="register-field">
          <span class="register-label">缓存刷新间隔（秒）</span>
          <Input v-model.number="config.clearance.refresh_interval" type="number" min="60" block :disabled="config.enabled || !config.clearance.enabled" />
        </label>

        <div class="register-clearance-test register-field--full">
          <Input :model-value="clearanceTestTarget" block root-class="font-mono" placeholder="https://auth.openai.com" @update:model-value="emit('update-clearance-test-target', String($event || '').trim())" />
          <Button size="sm" variant="outline" :disabled="clearanceTesting || !config.clearance.enabled" @click="emit('test-clearance')">
            {{ clearanceTesting ? '测试中...' : '按注册代理测试' }}
          </Button>
        </div>
        <div v-if="clearanceTestResult" class="register-clearance-result register-field--full">
          <p :class="clearanceTestResult.ok ? 'text-emerald-600' : 'text-rose-600'">
            {{ clearanceTestResult.ok ? `清障可用：${clearanceTestResult.latency_ms} ms` : `清障不可用：${clearanceTestResult.error || '未知错误'}` }}
          </p>
          <p v-if="clearanceTestResult.egress_label" class="text-muted-foreground">实际注册出口：{{ clearanceTestResult.egress_label }}</p>
          <p v-if="clearanceTestResult.user_agent" class="break-all text-muted-foreground">User-Agent：{{ clearanceTestResult.user_agent }}</p>
        </div>
      </div>
    </FormSection>

    <FormSection title="生图压力动态补号" density="roomy">
      <div class="register-form-grid">
        <label class="register-checkbox-field register-field--full">
          <Checkbox
            v-model="config.dynamic_image_scale_enabled"
            :disabled="config.enabled"
          >
            启用生图排队压力动态补号
          </Checkbox>
          <span class="register-checkbox-hint">目标可用账号 X 仍是保底值；生图请求排队时临时提高补号目标，低压后自动回落。</span>
        </label>

        <label class="register-field">
          <span class="register-label">最多额外补号</span>
          <Input
            v-model.number="config.dynamic_image_scale_max_extra"
            type="number"
            min="0"
            block
            :disabled="config.enabled || !config.dynamic_image_scale_enabled"
          />
        </label>

        <label class="register-field">
          <span class="register-label">压力持续（秒）</span>
          <Input
            v-model.number="config.dynamic_image_scale_pressure_seconds"
            type="number"
            min="1"
            block
            :disabled="config.enabled || !config.dynamic_image_scale_enabled"
          />
        </label>

        <label class="register-field">
          <span class="register-label">低压回落（秒）</span>
          <Input
            v-model.number="config.dynamic_image_scale_cooldown_seconds"
            type="number"
            min="1"
            block
            :disabled="config.enabled || !config.dynamic_image_scale_enabled"
          />
        </label>

        <label class="register-field">
          <span class="register-label">等待阈值（毫秒）</span>
          <Input
            v-model.number="config.dynamic_image_scale_wait_threshold_ms"
            type="number"
            min="0"
            step="500"
            block
            :disabled="config.enabled || !config.dynamic_image_scale_enabled"
          />
        </label>

        <label class="register-field">
          <span class="register-label">预留账号数</span>
          <Input
            v-model.number="config.dynamic_image_scale_buffer"
            type="number"
            min="0"
            block
            :disabled="config.enabled || !config.dynamic_image_scale_enabled"
          />
        </label>
      </div>
    </FormSection>

    <FormSection title="邮箱请求" density="roomy">
      <div class="register-form-grid register-form-grid--mail">
        <label class="register-field">
          <span class="register-label">请求超时（秒）</span>
          <Input
            v-model.number="config.mail.request_timeout"
            type="number"
            min="1"
            block
            :disabled="config.enabled"
          />
        </label>

        <label class="register-field">
          <span class="register-label">验证码等待（秒）</span>
          <Input
            v-model.number="config.mail.wait_timeout"
            type="number"
            min="1"
            block
            :disabled="config.enabled"
          />
        </label>

        <label class="register-field">
          <span class="register-label">轮询间隔（秒）</span>
          <Input
            v-model.number="config.mail.wait_interval"
            type="number"
            min="1"
            step="0.2"
            block
            :disabled="config.enabled"
          />
        </label>

        <label class="register-field register-field--full">
          <span class="register-label">请求 User-Agent</span>
          <Input
            v-model.trim="config.mail.user_agent"
            block
            root-class="font-mono"
            placeholder="留空使用默认 UA"
            :disabled="config.enabled"
          />
        </label>
      </div>
    </FormSection>
  </div>
</template>

<script setup lang="ts">
import { Button, Checkbox, Input } from 'nanocat-ui'

import FormSection from '@/components/ai/FormSection.vue'
import GroupedSelectMenu from '@/components/ui/GroupedSelectMenu.vue'
import type { LegacyRegisterConfig } from '@/api/register'
import type { ClearanceTestResult } from '@/types/api'
import {
  registerModeGroups,
  registerProxyModeGroups,
  type RegisterProxyMode,
} from '@/views/register/registerProviderView'

defineProps<{
  config: LegacyRegisterConfig
  proxyMode: RegisterProxyMode
  selectedProxyGroupId: string
  customProxyInput: string
  proxyGroupGroups: unknown[]
  proxyHint: string
  clearanceTestTarget: string
  clearanceTesting: boolean
  clearanceTestResult: ClearanceTestResult | null
}>()

const emit = defineEmits<{
  (e: 'update-proxy-mode', value: string): void
  (e: 'select-proxy-group', value: string): void
  (e: 'update-custom-proxy', value: string): void
  (e: 'update-clearance-test-target', value: string): void
  (e: 'test-clearance'): void
}>()

const clearanceModeGroups = [{ options: [
  { label: '关闭', value: 'none' },
  { label: 'FlareSolverr 自动清障', value: 'flaresolverr' },
  { label: '手动 Cookie', value: 'manual' },
] }]
</script>

<style scoped>
.register-task-settings {
  display: grid;
  gap: 16px;
}

.register-form-grid {
  display: grid;
  gap: 12px;
}

@media (min-width: 720px) {
  .register-form-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .register-field--full {
    grid-column: 1 / -1;
  }

  .register-form-grid--mail {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

.register-field {
  display: grid;
  min-width: 0;
  gap: 7px;
}

.register-label {
  font-size: 12px;
  color: hsl(var(--muted-foreground));
}

.register-clearance-test { display: flex; align-items: center; gap: 8px; }
.register-clearance-test :deep(.ui-input-root) { flex: 1; }
.register-clearance-result { display: grid; gap: 4px; border: 1px solid hsl(var(--border)); border-radius: 12px; padding: 10px 12px; font-size: 12px; }
.register-clearance-result p { margin: 0; }

.register-proxy-hint {
  margin: 0;
  font-size: 12px;
  line-height: 1.6;
  color: hsl(var(--muted-foreground));
}
</style>

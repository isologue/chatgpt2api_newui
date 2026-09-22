<template>
  <FormSection title="基础配置">
    <div class="grid grid-cols-1 gap-3 md:grid-cols-2">
      <FormField label="账号刷新间隔">
        <template #label-extra>
          <HelpTip text="单位分钟，控制账号自动刷新频率；保存设置后立即生效，无需重启服务。" />
        </template>
        <Input
          :model-value="refreshAccountIntervalField.input.value"
          type="number"
          block
          placeholder="5"
          @update:model-value="refreshAccountIntervalField.update"
        />
      </FormField>

      <FormField label="后端线程池容量">
        <template #label-extra>
          <HelpTip text="限制同步接口可同时占用的后端工作线程数。保存后立即生效，无需重启；调低时不会中断正在执行的请求，只会限制后续请求进入。" />
        </template>
        <Input
          :model-value="threadPoolCapacityField.input.value"
          type="number"
          block
          placeholder="80"
          @update:model-value="threadPoolCapacityField.update"
        />
      </FormField>

      <FormField label="图片访问地址">
        <template #label-extra>
          <HelpTip text="用于生成图片结果的访问前缀地址。" />
        </template>
        <Input
          v-model.trim="settings.base_url"
          block
          placeholder="https://example.com"
        />
      </FormField>

      <div class="md:col-span-2 rounded-xl border border-border bg-muted/20 px-3 py-3 text-xs leading-5 text-muted-foreground">
        默认出口、生图 A/B 分流、备用出口、Cloudflare 清障和出口监控已统一迁移到“代理管理”，避免多处配置互相覆盖。
      </div>
      <FormField label="图片自动清理">
        <template #label-extra>
          <HelpTip text="自动删除多少天前的本地图片。" />
        </template>
        <Input
          :model-value="imageRetentionDaysField.input.value"
          type="number"
          block
          placeholder="15"
          @update:model-value="imageRetentionDaysField.update"
        />
      </FormField>

      <FormField label="日志自动清理">
        <template #label-extra>
          <HelpTip text="自动删除多少天前的控制台调用日志，清理对象是 data/logs.jsonl。" />
        </template>
        <Input
          :model-value="logRetentionDaysField.input.value"
          type="number"
          block
          placeholder="30"
          @update:model-value="logRetentionDaysField.update"
        />
      </FormField>

      <FormField label="图片轮询超时">
        <template #label-extra>
          <HelpTip text="单位秒，等待上游图片结果的最长时间。" />
        </template>
        <Input
          :model-value="imagePollTimeoutField.input.value"
          type="number"
          block
          placeholder="60"
          @update:model-value="imagePollTimeoutField.update"
        />
      </FormField>

      <FormField label="上游流超时">
        <template #label-extra>
          <HelpTip text="单位秒，限制 ChatGPT 生图 SSE 流最长等待时间。" />
        </template>
        <Input
          :model-value="imageStreamTimeoutField.input.value"
          type="number"
          block
          placeholder="80"
          @update:model-value="imageStreamTimeoutField.update"
        />
      </FormField>

      <FormField label="单账号图片并发">
        <template #label-extra>
          <HelpTip text="限制每个账号同时处理的图片请求数量。默认 1，可设置为 1–3。" />
        </template>
        <Input
          :model-value="imageAccountConcurrencyField.input.value"
          type="number"
          block
          placeholder="1"
          @update:model-value="imageAccountConcurrencyField.update"
        />
      </FormField>

    </div>
  </FormSection>
</template>

<script setup lang="ts">
import { FormField, FormSection, HelpTip, Input } from 'nanocat-ui'
import type { Settings } from '@/types/api'
import type { NumberSettingField } from '@/views/settings/useNumberSettingField'

defineProps<{
  settings: Settings
  threadPoolCapacityField: NumberSettingField
  refreshAccountIntervalField: NumberSettingField
  imageRetentionDaysField: NumberSettingField
  logRetentionDaysField: NumberSettingField
  imagePollTimeoutField: NumberSettingField
  imageStreamTimeoutField: NumberSettingField
  imageAccountConcurrencyField: NumberSettingField
}>()
</script>

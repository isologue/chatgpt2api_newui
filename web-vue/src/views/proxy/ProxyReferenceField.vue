<template>
  <FormField :label="label">
    <template v-if="help" #label-extra>
      <HelpTip :text="help" />
    </template>
    <div class="grid gap-2 sm:grid-cols-[9rem_minmax(0,1fr)_auto]">
      <GroupedSelectMenu
        :model-value="mode"
        :options="modeOptions"
        :aria-label="`${label}类型`"
        selected-indicator="none"
        block
        @update:model-value="setMode"
      />
      <GroupedSelectMenu
        v-if="mode === 'group'"
        :model-value="groupId"
        :options="groupOptions"
        :aria-label="`${label}代理组`"
        selected-indicator="none"
        block
        @update:model-value="setGroup"
      />
      <Input
        v-else-if="mode === 'custom'"
        :model-value="customUrl"
        block
        root-class="font-mono"
        :placeholder="placeholder"
        @update:model-value="setCustom"
      />
      <div
        v-else
        class="flex min-h-10 items-center rounded-lg border border-dashed border-border bg-muted/20 px-3 text-xs text-muted-foreground"
      >
        {{ mode === 'direct' ? '故障时改为直连重试一次' : '不启用备用出口' }}
      </div>
      <Button
        size="sm"
        variant="outline"
        root-class="shrink-0"
        :disabled="testing || !canTest"
        @click="$emit('test')"
      >
        {{ testing ? '测试中...' : testLabel }}
      </Button>
    </div>
    <ProxyRouteTestResult :result="result" />
  </FormField>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { Button, FormField, HelpTip, Input } from 'nanocat-ui'

import { parseProxyReference, serializeProxyReference, type ProxyGroup, type ProxyTestResult } from '@/api/proxy'
import GroupedSelectMenu from '@/components/ui/GroupedSelectMenu.vue'
import ProxyRouteTestResult from '@/views/proxy/ProxyRouteTestResult.vue'

type RouteMode = 'off' | 'direct' | 'group' | 'custom'

const props = withDefaults(defineProps<{
  modelValue: string
  label: string
  groups: ProxyGroup[]
  help?: string
  placeholder?: string
  allowOff?: boolean
  allowDirect?: boolean
  testing?: boolean
  testLabel?: string
  result?: ProxyTestResult | null
}>(), {
  help: '',
  placeholder: 'http://127.0.0.1:7890 或 socks5://127.0.0.1:7890',
  allowOff: false,
  allowDirect: false,
  testing: false,
  testLabel: '测试',
  result: null,
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  change: []
  test: []
}>()

const lastCustom = ref('')
const lastGroup = ref('')

const reference = computed(() => parseProxyReference(props.modelValue))
const mode = computed<RouteMode>(() => {
  if (reference.value.mode === 'group') return 'group'
  if (reference.value.mode === 'direct' && props.allowDirect) return 'direct'
  if (reference.value.mode === 'global' && props.allowOff) return 'off'
  return 'custom'
})
const customUrl = computed(() => mode.value === 'custom' ? String(props.modelValue || '').trim() : lastCustom.value)
const groupId = computed(() => mode.value === 'group' ? reference.value.value : lastGroup.value)
const modeOptions = computed(() => [
  ...(props.allowOff ? [{ label: '关闭', value: 'off' }] : []),
  { label: '代理地址', value: 'custom' },
  { label: '代理组', value: 'group' },
  ...(props.allowDirect ? [{ label: '直连', value: 'direct' }] : []),
])
const groupOptions = computed(() => {
  const rows = props.groups.map((group) => ({
    label: `${group.enabled === false ? '停用 · ' : ''}${group.name || group.id}${Array.isArray(group.nodes) ? ` · ${group.nodes.length} 个节点` : ''}`,
    value: group.id,
  }))
  if (groupId.value && !rows.some((item) => item.value === groupId.value)) {
    rows.unshift({ label: `未知代理组 · ${groupId.value}`, value: groupId.value })
  }
  return [{ label: '选择代理组', value: '' }, ...rows]
})
const canTest = computed(() => {
  if (mode.value === 'off') return false
  if (mode.value === 'direct') return true
  if (mode.value === 'group') return Boolean(groupId.value)
  return Boolean(customUrl.value.trim())
})

watch(() => props.modelValue, (value) => {
  const parsed = parseProxyReference(value)
  if (parsed.mode === 'group') lastGroup.value = parsed.value
  else if (parsed.mode === 'custom' || parsed.mode === 'profile') lastCustom.value = String(value || '').trim()
}, { immediate: true })

function firstValue(value: string | string[]) {
  return Array.isArray(value) ? value[0] : value
}

function update(value: string) {
  emit('update:modelValue', value)
  emit('change')
}

function setMode(value: string | string[]) {
  const next = String(firstValue(value) || '') as RouteMode
  if (next === 'off') update('')
  else if (next === 'direct') update(serializeProxyReference('direct'))
  else if (next === 'group') update(serializeProxyReference('group', lastGroup.value))
  else update(lastCustom.value)
}

function setGroup(value: string | string[]) {
  lastGroup.value = String(firstValue(value) || '').trim()
  update(serializeProxyReference('group', lastGroup.value))
}

function setCustom(value: string) {
  lastCustom.value = String(value || '').trim()
  update(lastCustom.value)
}
</script>

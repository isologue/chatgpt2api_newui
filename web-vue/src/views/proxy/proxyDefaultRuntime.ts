import { computed, ref, type Ref } from 'vue'

import { normalizeProxyRuntime, prepareSettingsForEdit, settingsApi } from '@/api/settings'
import {
  parseProxyReference,
  proxyApi,
  type ProxyGroup,
  type ProxyRuntimeStatus,
  type ProxyTestResult,
} from '@/api/proxy'
import { useConfirmDialog } from '@/composables/useConfirmDialog'
import { usePageQuery } from '@/composables/usePageQuery'
import type { usePageRuntime } from '@/composables/usePageRuntime'
import { useSettingsStore } from '@/stores/settings'
import { useToast } from '@/composables/useToast'
import { errorMessage } from '@/lib/errorMessage'
import type { ProxyRuntimeSettings, Settings } from '@/types/api'
import { proxyActionError } from '@/views/proxy/proxyGroupRuntime'

export type ProxyRouteKey = 'control' | 'resource' | 'control_fallback' | 'resource_fallback'

type ProxyDefaultRuntimeOptions = {
  runtime: ReturnType<typeof usePageRuntime>
  requestKey: string
  groups: Ref<ProxyGroup[]>
  testingKey: Ref<string>
  updateGroups: (groups: ProxyGroup[]) => void
}

function cloneSettings(settings: Settings) {
  return prepareSettingsForEdit(settings)
}

function runtimeFingerprint(settings: Settings) {
  return JSON.stringify(normalizeProxyRuntime(settings.proxy_runtime))
}

function effectiveRuntimeForEdit(settings: Settings): ProxyRuntimeSettings {
  const runtime = normalizeProxyRuntime(settings.proxy_runtime)
  const legacyMain = String(settings.basic?.proxy || settings.proxy || '').trim()
  const legacyFallback = String(settings.fallback_proxy || '').trim()

  // 首次进入新版页面时，将仍在生效的旧版默认出口迁移到“单代理”，
  // 用户保存后顶层旧字段会被清空，后续只维护 proxy_runtime。
  if (!runtime.enabled && legacyMain && legacyMain.toLowerCase() !== 'direct') {
    runtime.enabled = true
    runtime.egress_mode = 'single_proxy'
    runtime.control_proxy_url = runtime.control_proxy_url || runtime.proxy_url || legacyMain
    runtime.control_fallback_proxy_url = runtime.control_fallback_proxy_url || legacyFallback
  } else {
    runtime.enabled = true
  }
  return runtime
}

function sanitizedRuntime(settings: Settings): ProxyRuntimeSettings {
  const runtime = normalizeProxyRuntime(settings.proxy_runtime)
  runtime.enabled = true
  if (runtime.egress_mode === 'direct') {
    runtime.proxy_url = ''
    runtime.control_proxy_url = ''
    runtime.resource_proxy_url = ''
    runtime.control_fallback_proxy_url = ''
    runtime.resource_fallback_proxy_url = ''
  } else if (runtime.egress_mode === 'single_proxy') {
    runtime.proxy_url = runtime.control_proxy_url
    runtime.resource_proxy_url = ''
    runtime.resource_fallback_proxy_url = ''
  } else {
    runtime.proxy_url = runtime.control_proxy_url
  }
  return runtime
}

function validateReference(value: string, label: string, required: boolean) {
  const reference = parseProxyReference(value)
  if (reference.mode === 'global' || (!reference.value && !['direct'].includes(reference.mode))) {
    if (required) return `${label}不能为空`
    return ''
  }
  if (reference.mode === 'group' && !reference.value) return `请选择${label}代理组`
  return ''
}

export function useProxyDefaultRuntime(options: ProxyDefaultRuntimeOptions) {
  const settingsStore = useSettingsStore()
  const toast = useToast()
  const confirmDialog = useConfirmDialog()
  const loading = ref(false)
  const savingDefaultProxy = ref(false)
  const currentSettings = ref<Settings | null>(null)
  const savedSettingsBaseline = ref<Settings | null>(null)
  const proxyRuntimeLoading = ref(false)
  const proxyRuntimeStatus = ref<ProxyRuntimeStatus | null>(null)
  const routeTestingKey = ref('')
  const routeTestResults = ref<Partial<Record<ProxyRouteKey, ProxyTestResult | null>>>({})

  const proxyDataQuery = usePageQuery({
    runtime: options.runtime,
    key: options.requestKey,
    loading,
    errorMessage: '加载代理配置失败',
  })
  const proxyRuntimeQuery = usePageQuery({
    runtime: options.runtime,
    key: `${options.requestKey}:runtime`,
    loading: proxyRuntimeLoading,
    errorMessage: '加载代理运行状态失败',
  })

  const isDefaultProxyDirty = computed(() => {
    const settings = currentSettings.value
    const baseline = savedSettingsBaseline.value
    return Boolean(settings && baseline && runtimeFingerprint(settings) !== runtimeFingerprint(baseline))
  })

  async function loadData() {
    await proxyDataQuery.run(
      () => Promise.all([settingsApi.get(), proxyApi.listGroups(), proxyApi.getRuntime()]),
      {
        apply: ([settings, groupResponse, runtimeResponse]) => {
          const next = prepareSettingsForEdit(settings)
          const runtimeSource = runtimeResponse.runtime || next.proxy_runtime
          next.proxy_runtime = effectiveRuntimeForEdit({ ...next, proxy_runtime: normalizeProxyRuntime(runtimeSource) })
          currentSettings.value = next
          savedSettingsBaseline.value = cloneSettings(next)
          proxyRuntimeStatus.value = runtimeResponse.status
          settingsStore.$patch({ settings })
          options.updateGroups(groupResponse.groups || [])
          routeTestResults.value = {}
        },
        onError: (message) => toast.error(message),
      },
    )
  }

  async function refreshRuntimeStatus(silent = false) {
    await proxyRuntimeQuery.run(
      () => proxyApi.getRuntime(),
      {
        apply: (response) => { proxyRuntimeStatus.value = response.status },
        onError: (message) => { if (!silent) toast.error(message) },
      },
    )
  }

  function validationError(runtime: ProxyRuntimeSettings) {
    if (runtime.egress_mode === 'single_proxy') {
      return validateReference(runtime.control_proxy_url, '主代理', true)
        || validateReference(runtime.control_fallback_proxy_url, '备用代理', false)
    }
    if (runtime.egress_mode === 'split_proxy') {
      return validateReference(runtime.control_proxy_url, '控制出口 B', true)
        || validateReference(runtime.resource_proxy_url, '资源出口 A', true)
        || validateReference(runtime.control_fallback_proxy_url, '控制备用出口', false)
        || validateReference(runtime.resource_fallback_proxy_url, '资源备用出口', false)
    }
    return ''
  }

  async function saveDefaultProxy() {
    if (!currentSettings.value) {
      toast.warning('配置尚未加载完成')
      return
    }
    const next = prepareSettingsForEdit(currentSettings.value)
    next.proxy_runtime = sanitizedRuntime(next)
    const invalid = validationError(next.proxy_runtime)
    if (invalid) {
      toast.warning(invalid)
      return
    }
    const confirmed = await confirmDialog.ask({
      title: '确认保存出站路由',
      message: '将保存当前出站方式、主备代理、A/B 分流和 Cloudflare 清障配置。旧版默认/备用出口字段会清空，新请求立即生效，已建立的 SSE 不会中途切换。是否继续？',
      confirmText: '保存',
      cancelText: '取消',
    })
    if (!confirmed) return

    savingDefaultProxy.value = true
    try {
      // 顶层 proxy/fallback_proxy 仅用于读取旧配置迁移；保存后统一由 proxy_runtime 管理。
      next.proxy = ''
      next.fallback_proxy = ''
      const response = await settingsStore.updateSettingsPatch({
        proxy: '',
        fallback_proxy: '',
        proxy_runtime: next.proxy_runtime,
      })
      const applied = prepareSettingsForEdit(response.config || next)
      applied.proxy_runtime = effectiveRuntimeForEdit(applied)
      currentSettings.value = applied
      savedSettingsBaseline.value = cloneSettings(applied)
      await refreshRuntimeStatus(true)
      toast.success('出站路由已保存，新请求已实时生效')
    } catch (error) {
      toast.error(proxyActionError('保存出站路由失败', error))
    } finally {
      savingDefaultProxy.value = false
    }
  }

  async function executeProxyTest(candidate: string, label: string): Promise<ProxyTestResult> {
    const reference = parseProxyReference(candidate)
    if (reference.mode === 'global' || reference.mode === 'direct') {
      return { ok: true, status: 0, latency_ms: 0, error: `${label}当前为直连，无需代理连通性测试` }
    }
    if (reference.mode === 'group') {
      if (!reference.value) throw new Error(`${label}缺少代理组 ID`)
      const response = await proxyApi.testGroup({ id: reference.value })
      if (response.groups) options.updateGroups(response.groups)
      const results = response.results || []
      const failed = results.filter((item) => !item.result.ok)
      const firstResult = results[0]?.result
      return {
        ok: results.length > 0 && failed.length === 0,
        status: firstResult?.status || 0,
        latency_ms: results.reduce((max, item) => Math.max(max, Number(item.result.latency_ms || 0)), 0),
        error: failed.length ? `代理组检测完成，失败 ${failed.length} 个节点` : null,
      }
    }
    if (reference.mode === 'profile') {
      if (!reference.value) throw new Error(`${label}缺少历史代理配置 ID`)
      return (await proxyApi.testProfile({ id: reference.value })).result
    }
    if (!reference.value) throw new Error(`${label}代理地址为空`)
    return (await proxyApi.test(reference.value)).result
  }

  function routeReference(key: ProxyRouteKey) {
    const settings = currentSettings.value
    if (!settings) return ''
    const runtime = sanitizedRuntime(settings)
    if (runtime.egress_mode === 'direct') return key.includes('fallback') ? '' : 'direct'
    if (runtime.egress_mode === 'single_proxy') {
      return key.includes('fallback') ? runtime.control_fallback_proxy_url : runtime.control_proxy_url
    }
    if (key === 'control') return runtime.control_proxy_url
    if (key === 'resource') return runtime.resource_proxy_url
    if (key === 'control_fallback') return runtime.control_fallback_proxy_url
    return runtime.resource_fallback_proxy_url || runtime.control_proxy_url
  }

  function routeLabel(key: ProxyRouteKey) {
    const mode = currentSettings.value?.proxy_runtime?.egress_mode
    if (mode === 'single_proxy') return key.includes('fallback') ? '备用代理' : '主代理'
    const labels: Record<ProxyRouteKey, string> = {
      control: '控制出口 B',
      resource: '资源出口 A',
      control_fallback: '控制备用出口',
      resource_fallback: '资源备用出口',
    }
    return labels[key]
  }

  async function testProxyRoute(key: ProxyRouteKey) {
    const label = routeLabel(key)
    const candidate = routeReference(key)
    if (!candidate) {
      toast.info(`${label}未配置`)
      return
    }
    const confirmed = await confirmDialog.ask({
      title: `测试${label}`,
      message: `将按当前页面配置测试${label}，不会保存设置。是否继续？`,
      confirmText: '开始测试',
      cancelText: '取消',
    })
    if (!confirmed) return

    routeTestingKey.value = key
    routeTestResults.value = { ...routeTestResults.value, [key]: null }
    try {
      const result = await executeProxyTest(candidate, label)
      routeTestResults.value = { ...routeTestResults.value, [key]: result }
      if (result.ok) toast.success(`${label}可用${result.latency_ms ? `，耗时 ${result.latency_ms}ms` : ''}`)
      else toast.warning(result.error || `${label}测试失败`)
    } catch (error) {
      const message = errorMessage(error, `${label}测试失败`)
      routeTestResults.value = { ...routeTestResults.value, [key]: { ok: false, status: 0, latency_ms: 0, error: message } }
      toast.error(message)
    } finally {
      routeTestingKey.value = ''
    }
  }

  function clearProxyRouteResult(key: ProxyRouteKey) { routeTestResults.value = { ...routeTestResults.value, [key]: null } }
  function invalidate() { proxyDataQuery.invalidate(); proxyRuntimeQuery.invalidate() }

  return {
    loading,
    savingDefaultProxy,
    currentSettings,
    isDefaultProxyDirty,
    proxyRuntimeLoading,
    proxyRuntimeStatus,
    routeTestingKey,
    routeTestResults,
    loadData,
    refreshRuntimeStatus,
    saveDefaultProxy,
    testProxyRoute,
    clearProxyRouteResult,
    invalidate,
  }
}

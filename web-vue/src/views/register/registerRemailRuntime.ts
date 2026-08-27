import { ref, type ComputedRef } from 'vue'

import { registerApi, type RegisterProvider, type RemailProject } from '@/api/register'
import { providerType, sanitizedProviderPayload } from '@/views/register/registerProviderView'

type MetaChipTone = 'default' | 'muted' | 'success' | 'warning' | 'danger' | 'info'

type RegisterRemailRuntimeInput = {
  providers: ComputedRef<RegisterProvider[]>
  notifySuccess: (message: string) => void
  notifyError: (message: string) => void
}

export type RemailCatalogState = {
  loading: boolean
  error: string
  projects: RemailProject[]
  count: number
  loadedAt: number
}

type SelectGroup = {
  label?: string
  options: Array<{ label: string; value: string; disabled?: boolean }>
}

const emptyState = (): RemailCatalogState => ({ loading: false, error: '', projects: [], count: 0, loadedAt: 0 })

function suffixLabel(suffix: { suffix?: string; total_available?: number; public_available?: number }) {
  const name = String(suffix.suffix || '').trim()
  const total = Number(suffix.total_available || 0)
  const pub = Number(suffix.public_available || 0)
  if (total || pub) return `${name}（可用 ${total} / 公库 ${pub}）`
  return name
}

export function useRegisterRemailRuntime(input: RegisterRemailRuntimeInput) {
  const states = ref<Record<number, RemailCatalogState>>({})

  function stateByIndex(index: number) {
    return states.value[index] || null
  }

  function ensureState(index: number) {
    if (!states.value[index]) states.value[index] = emptyState()
    return states.value[index]
  }

  function clearState(index: number) {
    const next = { ...states.value }
    delete next[index]
    states.value = next
  }

  function clearAllStates() {
    states.value = {}
  }

  function pruneStates() {
    const providers = input.providers.value
    const next: Record<number, RemailCatalogState> = {}
    providers.forEach((provider, index) => {
      if (providerType(provider) === 'remail' && states.value[index]) next[index] = states.value[index]
    })
    states.value = next
  }

  function projects(index: number) {
    return stateByIndex(index)?.projects || []
  }

  function hasProjectOptions(index: number) {
    return projects(index).length > 0
  }

  function currentProject(index: number, provider: RegisterProvider) {
    const value = String(provider.project_id || '').trim()
    return projects(index).find(project => String(project.id) === value) || null
  }

  function projectGroups(index: number, provider: RegisterProvider): SelectGroup[] {
    const options = projects(index).map(project => ({
      label: `${project.name || `Project ${project.id}`}（${project.suffixes?.length || 0} 个后缀）`,
      value: String(project.id),
    }))
    const selected = String(provider.project_id || '').trim()
    if (selected && !options.some(option => option.value === selected)) {
      options.unshift({ label: `当前项目 ${selected}`, value: selected })
    }
    return [{ options }]
  }

  function suffixGroups(index: number, provider: RegisterProvider): SelectGroup[] {
    const selectedProject = currentProject(index, provider)
    const suffixes = selectedProject?.suffixes || []
    const options = suffixes.map(suffix => ({ label: suffixLabel(suffix), value: String(suffix.suffix || '').trim() }))
    const selected = String(provider.email_suffix || '').trim()
    if (selected && !options.some(option => option.value === selected)) {
      options.unshift({ label: `当前后缀 ${selected}`, value: selected })
    }
    return [{ options }]
  }

  function hasSuffixOptions(index: number, provider: RegisterProvider) {
    return Boolean(currentProject(index, provider)?.suffixes?.length)
  }

  function statusTone(index: number): MetaChipTone {
    const state = stateByIndex(index)
    if (!state) return 'muted'
    if (state.loading) return 'info'
    if (state.error) return 'danger'
    if (state.count > 0) return 'success'
    return 'warning'
  }

  function statusText(index: number) {
    const state = stateByIndex(index)
    if (!state) return '未读取项目'
    if (state.loading) return '正在读取'
    if (state.error) return '读取失败'
    return `可用项目 ${state.count}`
  }

  async function loadProjects(index: number, provider: RegisterProvider, options: { silent?: boolean } = {}) {
    const state = ensureState(index)
    state.loading = true
    state.error = ''
    try {
      const response = await registerApi.getRemailProjects(sanitizedProviderPayload(provider))
      state.projects = Array.isArray(response.projects) ? response.projects : []
      state.count = Number(response.count || state.projects.length) || 0
      state.loadedAt = Date.now()

      const selectedProject = currentProject(index, provider) || state.projects[0]
      if (selectedProject && !String(provider.project_id || '').trim()) {
        provider.project_id = String(selectedProject.id)
      }
      const selectedSuffix = currentProject(index, provider)?.suffixes?.[0]
      if (selectedSuffix && !String(provider.email_suffix || '').trim()) {
        provider.email_suffix = String(selectedSuffix.suffix || '')
      }
      if (!options.silent) input.notifySuccess(`已读取 ${state.count} 个 Remail 可用项目`)
    } catch (error: any) {
      const message = error?.message || '读取 Remail 项目列表失败'
      state.error = message
      if (!options.silent) input.notifyError(message)
    } finally {
      state.loading = false
    }
  }

  return {
    stateByIndex,
    clearState,
    clearAllStates,
    pruneStates,
    hasProjectOptions,
    hasSuffixOptions,
    projectGroups,
    suffixGroups,
    statusTone,
    statusText,
    loadProjects,
  }
}

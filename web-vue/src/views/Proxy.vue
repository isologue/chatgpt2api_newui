<template>
  <div class="space-y-6">
    <PagePanel class="space-y-5">
      <PanelHeader title="代理管理 / 出口路由" align="start">
        <template #copy>
          <p class="mt-1 text-xs text-muted-foreground">
            代理路由统一在这里维护。根据出站方式选择直连、单代理或 A/B 分流；保存后对新请求实时生效。
          </p>
        </template>
        <template #actions>
          <Button size="sm" variant="outline" :disabled="loading" @click="loadData">
            {{ loading ? '刷新中...' : '刷新' }}
          </Button>
          <Button size="sm" variant="primary" :disabled="savingDefaultProxy || loading" @click="saveDefaultProxy">
            {{ savingDefaultProxy ? '保存中...' : '保存出站路由' }}
          </Button>
        </template>
      </PanelHeader>

      <SettingsProxyRuntimePanel
        v-if="currentSettings"
        :settings="currentSettings"
        :groups="groups"
        :runtime-status="proxyRuntimeStatus"
        :route-testing-key="routeTestingKey"
        :route-test-results="routeTestResults"
        @clear-proxy-route-result="clearProxyRouteResult"
        @test-proxy-route="testProxyRoute"
      />
    </PagePanel>

    <PagePanel class="space-y-4">
      <PanelHeader title="代理组 / 多出口">
        <template #copy>
          <p class="mt-1 text-xs text-muted-foreground">
            一个代理组就是一组多出口节点；图片请求会从未满的节点里随机选择一个，请求结束前固定该出口，出口满了会等待，不会自动绕到直连。
          </p>
        </template>
        <template #actions>
          <Input
            :model-value="groupKeyword"
            block
            root-class="min-w-[12rem] md:w-80"
            placeholder="搜索代理组 / 节点 / 地址"
            @update:model-value="groupKeyword = $event.trim()"
          />
          <Button size="sm" variant="primary" @click="openCreateGroupModal">新建代理组</Button>
        </template>
      </PanelHeader>
      <PageLoadingState
        v-if="loading && groups.length === 0"
        title="正在加载代理组"
        description="读取代理组、节点和健康状态。"
      />
      <StateBlock v-else-if="filteredGroups.length === 0">
        <EmptyState plain title="暂无代理组" description="新建代理组后，可绑定账号组、账号或出站路由使用。" />
      </StateBlock>
      <TableShell v-else>
        <table class="min-w-[1080px] w-full table-fixed text-left text-sm">
          <colgroup>
            <col class="w-[20%]" />
            <col class="w-[7rem]" />
            <col class="w-[30%]" />
            <col class="w-[15%]" />
            <col class="w-[16%]" />
            <col class="w-[16rem]" />
          </colgroup>
          <thead class="text-xs uppercase tracking-[0.16em] text-muted-foreground">
            <tr>
              <th class="py-3 pr-4">代理组</th>
              <th class="py-3 pr-4">状态</th>
              <th class="py-3 pr-4">节点</th>
              <th class="py-3 pr-4">引用</th>
              <th class="py-3 pr-4">健康</th>
              <th class="py-3 text-right">操作</th>
            </tr>
          </thead>
          <tbody class="text-sm text-foreground">
            <ProxyGroupRow
              v-for="group in filteredGroups"
              :key="group.id"
              :group="group"
              :testing-key="testingKey"
              :saving-group-id="savingGroupId"
              :deleting-group-id="deletingGroupId"
              :node-test-summary="nodeTestSummary"
              :node-test-class="nodeTestClass"
              @copy-reference="copyProxyGroupReference"
              @edit="openEditGroupModal"
              @action="handleProxyGroupAction"
            />
          </tbody>
        </table>
      </TableShell>
    </PagePanel>

    <ModalShell :open="showGroupModal" max-width="56rem" :z-index="120">
      <ModalHeader
        :title="editingGroupId ? '编辑代理组' : '新建代理组'"
        :close-disabled="savingGroupId === FORM_TEST_KEY"
        :bordered="false"
        compact
        @close="closeGroupModal"
      />

      <ModalBody class="space-y-4">
        <FormSection title="基础信息" surface="plain">
              <div class="grid grid-cols-1 gap-2.5 md:grid-cols-[minmax(0,1fr)_16rem]">
                <label class="text-xs">
                  <span class="ui-field-label">代理组名称</span>
                  <Input
                    :model-value="groupForm.name"
                    block
                    placeholder="香港代理池"
                    @update:model-value="groupForm.name = $event.trim()"
                  />
                </label>
                <label class="text-xs">
                  <span class="ui-field-label">代理组 ID</span>
                  <Input
                    :model-value="groupForm.id"
                    block
                    root-class="font-mono"
                    :disabled="Boolean(editingGroupId)"
                    @update:model-value="groupForm.id = normalizeGroupId($event)"
                  />
                </label>
              </div>
              <div class="grid grid-cols-1 gap-2.5 md:grid-cols-[minmax(0,1fr)_auto]">
                <label class="text-xs">
                  <span class="ui-field-label">备注</span>
                  <Input
                    :model-value="groupForm.notes"
                    block
                    placeholder="可选"
                    @update:model-value="groupForm.notes = $event.trim()"
                  />
                </label>
                <div class="flex items-end">
                  <Checkbox v-model="groupForm.enabled">启用代理组</Checkbox>
                </div>
              </div>
        </FormSection>

              <div class="space-y-3">
                <div class="flex flex-wrap items-center justify-between gap-2">
                  <p class="text-xs font-medium text-foreground">代理节点</p>
                  <Button size="xs" variant="outline" @click="addGroupNode">添加节点</Button>
                </div>
                <div class="space-y-3">
                  <FormSection
                    v-for="(node, index) in groupForm.nodes"
                    :key="`${node.id}-${index}`"
                    surface="muted"
                  >
                    <div class="grid grid-cols-1 gap-2 md:grid-cols-[10rem_minmax(0,1fr)_8rem_auto]">
                      <label class="text-xs">
                        <span class="ui-field-label">名称</span>
                        <Input
                          :model-value="node.name"
                          block
                          @update:model-value="node.name = $event.trim()"
                        />
                      </label>
                      <label class="text-xs">
                        <span class="ui-field-label">代理 URL</span>
                        <Input
                          :model-value="node.url"
                          block
                          root-class="font-mono"
                          placeholder="http://user:password@host:port"
                          @update:model-value="node.url = $event.trim()"
                        />
                      </label>
                      <label class="text-xs">
                        <span class="ui-field-label">图片并发</span>
                        <Input
                          :model-value="String(node.image_concurrency_limit ?? 0)"
                          block
                          type="number"
                          min="0"
                          step="1"
                          placeholder="默认 30，0 不限"
                          title="限制该节点同时处理的图片请求数；超出后等待同组节点空位，不会改走直连。0 表示不限制。"
                          @update:model-value="node.image_concurrency_limit = normalizeImageConcurrencyLimit($event)"
                        />
                      </label>
                      <div class="flex items-end gap-2">
                        <Checkbox v-model="node.enabled">启用</Checkbox>
                      </div>
                    </div>
                    <div class="mt-2 flex flex-wrap items-center justify-between gap-2">
                      <label class="min-w-[12rem] flex-1 text-xs">
                        <span class="ui-field-label">备注</span>
                        <Input
                          :model-value="node.notes || ''"
                          block
                          placeholder="可选"
                          @update:model-value="node.notes = $event.trim()"
                        />
                      </label>
                      <div class="flex items-end gap-2 pt-5">
                        <Button
                          size="xs"
                          variant="outline"
                          :disabled="!editingGroupId || !node.url || testingKey === `group:${editingGroupId}:${node.id}`"
                          @click="testProxyGroupNode({ id: editingGroupId, name: groupForm.name }, node)"
                        >
                          {{ testingKey === `group:${editingGroupId}:${node.id}` ? '检测中...' : '检测' }}
                        </Button>
                        <Button size="xs" variant="outline" root-class="text-rose-600" @click="removeGroupNode(index)">
                          删除
                        </Button>
                      </div>
                    </div>
                  </FormSection>
                </div>
              </div>
      </ModalBody>

      <ModalFooter :bordered="false">
        <Button size="xs" variant="outline" root-class="min-w-14 justify-center" :disabled="savingGroupId === FORM_TEST_KEY" @click="closeGroupModal">
          取消
        </Button>
        <Button size="xs" variant="primary" root-class="min-w-14 justify-center" :disabled="savingGroupId === FORM_TEST_KEY" @click="saveProxyGroup">
          {{ savingGroupId === FORM_TEST_KEY ? '保存中...' : editingGroupId ? '更新' : '保存' }}
        </Button>
      </ModalFooter>
    </ModalShell>

  </div>
</template>

<script setup lang="ts">
import { Button, Checkbox, EmptyState, Input } from 'nanocat-ui'
import FormSection from '@/components/ai/FormSection.vue'
import ModalBody from '@/components/ai/ModalBody.vue'
import ModalFooter from '@/components/ai/ModalFooter.vue'
import ModalHeader from '@/components/ai/ModalHeader.vue'
import ModalShell from '@/components/ai/ModalShell.vue'
import PageLoadingState from '@/components/ai/PageLoadingState.vue'
import PagePanel from '@/components/ai/PagePanel.vue'
import PanelHeader from '@/components/ai/PanelHeader.vue'
import StateBlock from '@/components/ai/StateBlock.vue'
import TableShell from '@/components/ai/TableShell.vue'
import { usePageRuntime } from '@/composables/usePageRuntime'
import { useProxyDefaultRuntime } from '@/views/proxy/proxyDefaultRuntime'
import {
  FORM_TEST_KEY,
  normalizeGroupId,
  normalizeImageConcurrencyLimit,
  useProxyGroupRuntime,
} from '@/views/proxy/proxyGroupRuntime'
import ProxyGroupRow from '@/views/proxy/ProxyGroupRow.vue'
import SettingsProxyRuntimePanel from '@/views/settings/SettingsProxyRuntimePanel.vue'

defineOptions({ name: 'Proxy' })

const proxyGroupsRuntime = useProxyGroupRuntime()
const savingGroupId = proxyGroupsRuntime.savingGroupId
const deletingGroupId = proxyGroupsRuntime.deletingGroupId
const testingKey = proxyGroupsRuntime.testingKey
const groupKeyword = proxyGroupsRuntime.groupKeyword
const showGroupModal = proxyGroupsRuntime.showGroupModal
const editingGroupId = proxyGroupsRuntime.editingGroupId
const groups = proxyGroupsRuntime.groups
const groupForm = proxyGroupsRuntime.groupForm
const filteredGroups = proxyGroupsRuntime.filteredGroups
const updateGroups = proxyGroupsRuntime.updateGroups
const copyProxyGroupReference = proxyGroupsRuntime.copyProxyGroupReference
const openCreateGroupModal = proxyGroupsRuntime.openCreateGroupModal
const openEditGroupModal = proxyGroupsRuntime.openEditGroupModal
const closeGroupModal = proxyGroupsRuntime.closeGroupModal
const addGroupNode = proxyGroupsRuntime.addGroupNode
const removeGroupNode = proxyGroupsRuntime.removeGroupNode
const saveProxyGroup = proxyGroupsRuntime.saveProxyGroup
const handleProxyGroupAction = proxyGroupsRuntime.handleProxyGroupAction
const testProxyGroupNode = proxyGroupsRuntime.testProxyGroupNode
const nodeTestSummary = proxyGroupsRuntime.nodeTestSummary
const nodeTestClass = proxyGroupsRuntime.nodeTestClass
const pageRuntime = usePageRuntime('proxy')
const PROXY_DATA_REQUEST_KEY = 'proxy:data'
const proxyDefaultRuntime = useProxyDefaultRuntime({
  runtime: pageRuntime,
  requestKey: PROXY_DATA_REQUEST_KEY,
  groups,
  testingKey,
  updateGroups,
})
const loading = proxyDefaultRuntime.loading
const savingDefaultProxy = proxyDefaultRuntime.savingDefaultProxy
const isDefaultProxyDirty = proxyDefaultRuntime.isDefaultProxyDirty
const loadData = proxyDefaultRuntime.loadData
const saveDefaultProxy = proxyDefaultRuntime.saveDefaultProxy
const currentSettings = proxyDefaultRuntime.currentSettings
const proxyRuntimeStatus = proxyDefaultRuntime.proxyRuntimeStatus
const routeTestingKey = proxyDefaultRuntime.routeTestingKey
const routeTestResults = proxyDefaultRuntime.routeTestResults
const testProxyRoute = proxyDefaultRuntime.testProxyRoute
const clearProxyRouteResult = proxyDefaultRuntime.clearProxyRouteResult


function deactivateProxyView() {
  proxyDefaultRuntime.invalidate()
}

pageRuntime.onActivate(({ initial }) => {
  if (initial) {
    void loadData()
    return
  }
  if (showGroupModal.value || savingDefaultProxy.value || savingGroupId.value || testingKey.value || isDefaultProxyDirty.value) return
  void loadData()
})

pageRuntime.onDeactivate(() => {
  deactivateProxyView()
})

pageRuntime.onHide(() => {
  deactivateProxyView()
})

pageRuntime.onShow(() => {
  if (showGroupModal.value || savingDefaultProxy.value || savingGroupId.value || testingKey.value || isDefaultProxyDirty.value) return
  void loadData()
})
</script>

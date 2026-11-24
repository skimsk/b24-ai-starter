import { withoutTrailingSlash } from 'ufo'

export interface ModulbankStatus {
  connected: boolean
  hasCredentials: boolean
  sandbox: boolean
  companyName: string | null
  companyInn: string | null
  /** Адрес для уведомлений о новых операциях: вставляется в личном кабинете Модульбанка. */
  webhookUrl: string | null
  lastSyncAt: string | null
}

export interface ModulbankAccount {
  accountId: string
  number: string
  name?: string
  category: string
  currency: string
  status: string
  balance: number | null
  bankName?: string
  bankBic?: string
  companyId: string
  companyName?: string
}

export type ModulbankSyncParams =
  | { days: number }
  | { startDate: string; endDate: string }

const EMPTY_STATUS: ModulbankStatus = {
  connected: false,
  hasCredentials: false,
  sandbox: false,
  companyName: null,
  companyInn: null,
  webhookUrl: null,
  lastSyncAt: null,
}

interface ApiFetchError {
  message?: string
  data?: { error?: string; needReconnect?: boolean }
}

function errorText(e: unknown, fallback: string): string {
  const err = e as ApiFetchError
  return err?.data?.error || err?.message || fallback
}

function needsReconnect(e: unknown): boolean {
  return (e as ApiFetchError)?.data?.needReconnect === true
}

export const useModulbankStore = defineStore('modulbank', () => {
  const config = useRuntimeConfig()
  const apiStore = useApiStore()
  const $api = $fetch.create({
    baseURL: withoutTrailingSlash(config.public.apiUrl),
    headers: { 'Content-Type': 'application/json' },
  })

  const status = ref<ModulbankStatus>({ ...EMPTY_STATUS })
  const accounts = ref<ModulbankAccount[]>([])
  const isLoading = ref(false)
  const isSyncing = ref(false)
  const error = ref<string | null>(null)

  function auth() {
    return { Authorization: `Bearer ${apiStore.tokenJWT}` }
  }

  async function fetchStatus() {
    try {
      status.value = { ...EMPTY_STATUS, ...(await $api<ModulbankStatus>('/api/modulbank/status', { headers: auth() })) }
    } catch {
      status.value = { ...EMPTY_STATUS }
    }
  }

  async function connect(opts: { apiToken?: string; sandbox?: boolean }) {
    isLoading.value = true
    error.value = null
    try {
      await $api('/api/modulbank/connect', {
        method: 'POST',
        headers: auth(),
        body: JSON.stringify(opts.sandbox ? { sandbox: true } : { apiToken: opts.apiToken }),
      })
      await fetchStatus()
    } catch (e: unknown) {
      error.value = errorText(e, 'Не удалось подключить Модульбанк')
      throw e
    } finally {
      isLoading.value = false
    }
  }

  async function disconnect() {
    isLoading.value = true
    try {
      await $api('/api/modulbank/disconnect', { method: 'POST', headers: auth() })
      accounts.value = []
      await fetchStatus()
    } finally {
      isLoading.value = false
    }
  }

  async function fetchAccounts() {
    error.value = null
    try {
      const data = await $api<{ accounts: ModulbankAccount[] }>('/api/modulbank/accounts', { headers: auth() })
      accounts.value = data.accounts || []
    } catch (e: unknown) {
      error.value = errorText(e, 'Не удалось получить счета')
      if (needsReconnect(e)) await fetchStatus()
    }
  }

  async function sync(params: ModulbankSyncParams = { days: 30 }) {
    isSyncing.value = true
    error.value = null
    try {
      const result = await $api<{ synced: number; lastSync: string }>('/api/modulbank/sync', {
        method: 'POST',
        headers: auth(),
        body: JSON.stringify(params),
      })
      status.value.lastSyncAt = result.lastSync
      return result
    } catch (e: unknown) {
      error.value = errorText(e, 'Не удалось загрузить выписку')
      if (needsReconnect(e)) await fetchStatus()
      throw e
    } finally {
      isSyncing.value = false
    }
  }

  return { status, accounts, isLoading, isSyncing, error, fetchStatus, connect, disconnect, fetchAccounts, sync }
})

<script setup lang="ts">
/**
 * Подключение Модульбанка по ключу API из личного кабинета банка.
 * Ключ: ЛК Модульбанка → Настройки → API, права account-info и operation-history.
 */
const emit = defineEmits<{ (e: 'connected'): void }>()

const store = useModulbankStore()
const apiToken = ref('')
const syncMessage = ref('')
const copied = ref(false)

onMounted(async () => {
  await store.fetchStatus()
  if (store.status.connected) await store.fetchAccounts()
})

async function handleConnect(sandbox = false) {
  syncMessage.value = ''
  try {
    await store.connect(sandbox ? { sandbox: true } : { apiToken: apiToken.value.trim() })
    apiToken.value = ''
    await store.fetchAccounts()
    emit('connected')
  } catch {
    // текст ошибки уже в store.error
  }
}

async function handleSync() {
  syncMessage.value = ''
  try {
    const result = await store.sync({ days: 30 })
    syncMessage.value = `Загружено операций за 30 дней: ${result.synced}`
  } catch {
    // текст ошибки уже в store.error
  }
}

async function copyWebhook() {
  if (!store.status.webhookUrl) return
  try {
    await navigator.clipboard.writeText(store.status.webhookUrl)
    copied.value = true
    setTimeout(() => { copied.value = false }, 2000)
  } catch {
    copied.value = false
  }
}

function formatBalance(value: number | null, currency: string) {
  if (value == null) return '—'
  return new Intl.NumberFormat('ru-RU', { style: 'currency', currency: currency === 'RUR' ? 'RUB' : currency || 'RUB' }).format(value)
}
</script>

<template>
  <section class="mb-connect">
    <h2 class="mb-connect__title">Модульбанк</h2>

    <template v-if="!store.status.connected">
      <p class="mb-connect__text">
        Создайте ключ API в личном кабинете Модульбанка (Настройки → API) с правами
        «account-info» и «operation-history» и вставьте его сюда.
      </p>
      <form class="mb-connect__form" @submit.prevent="handleConnect(false)">
        <input
          v-model="apiToken"
          class="mb-connect__input"
          type="password"
          autocomplete="off"
          placeholder="Ключ API Модульбанка"
        >
        <button
          type="submit"
          class="mb-connect__btn mb-connect__btn--primary"
          :disabled="store.isLoading || !apiToken.trim()"
        >
          {{ store.isLoading ? 'Проверяю ключ…' : 'Подключить' }}
        </button>
      </form>
      <button type="button" class="mb-connect__link" :disabled="store.isLoading" @click="handleConnect(true)">
        Попробовать на тестовых данных банка
      </button>
    </template>

    <template v-else>
      <p class="mb-connect__text">
        Подключено: <b>{{ store.status.companyName || 'компания' }}</b>
        <span v-if="store.status.companyInn">, ИНН {{ store.status.companyInn }}</span>
        <span v-if="store.status.sandbox" class="mb-connect__badge">тестовые данные</span>
      </p>

      <ul v-if="store.accounts.length" class="mb-connect__accounts">
        <li v-for="account in store.accounts" :key="account.accountId">
          <span>{{ account.name || account.category }} · {{ account.number }}</span>
          <b>{{ formatBalance(account.balance, account.currency) }}</b>
        </li>
      </ul>

      <div v-if="store.status.webhookUrl" class="mb-connect__webhook">
        <p class="mb-connect__text">
          Чтобы платежи приходили сразу, вставьте этот адрес в личном кабинете Модульбанка
          в настройках уведомлений об операциях:
        </p>
        <div class="mb-connect__form">
          <input class="mb-connect__input" :value="store.status.webhookUrl" readonly>
          <button type="button" class="mb-connect__btn" @click="copyWebhook">
            {{ copied ? 'Скопировано' : 'Копировать' }}
          </button>
        </div>
      </div>

      <div class="mb-connect__actions">
        <button type="button" class="mb-connect__btn mb-connect__btn--primary" :disabled="store.isSyncing" @click="handleSync">
          {{ store.isSyncing ? 'Загружаю выписку…' : 'Загрузить выписку за 30 дней' }}
        </button>
        <button type="button" class="mb-connect__btn" :disabled="store.isLoading" @click="store.disconnect()">
          Отключить
        </button>
      </div>
      <p v-if="syncMessage" class="mb-connect__ok">{{ syncMessage }}</p>
    </template>

    <p v-if="store.error" class="mb-connect__error">{{ store.error }}</p>
  </section>
</template>

<style scoped>
.mb-connect { max-width: 560px; margin: 0 auto; padding: 1.5rem 1rem; box-sizing: border-box; }
.mb-connect__title { font-size: 1.25rem; font-weight: 600; margin: 0 0 .75rem; }
.mb-connect__text { margin: 0 0 .75rem; color: #374151; line-height: 1.45; }
.mb-connect__form { display: flex; gap: .5rem; margin-bottom: .75rem; flex-wrap: wrap; }
.mb-connect__input { flex: 1 1 240px; min-width: 0; padding: .55rem .75rem; border: 1px solid #d1d5db; border-radius: .5rem; font: inherit; }
.mb-connect__btn { padding: .55rem 1rem; border: 1px solid #d1d5db; border-radius: .5rem; background: #fff; font: inherit; cursor: pointer; }
.mb-connect__btn--primary { background: var(--mb-primary); border-color: var(--mb-primary); color: var(--mb-on-primary); }
.mb-connect__btn--primary:hover:not(:disabled) { background: var(--mb-primary-hover); border-color: var(--mb-primary-hover); }
.mb-connect__btn:disabled { opacity: .55; cursor: default; }
.mb-connect__link { background: none; border: 0; padding: 0; color: var(--mb-accent); cursor: pointer; font: inherit; }
.mb-connect__badge { margin-left: .5rem; padding: .1rem .45rem; border-radius: .35rem; background: #fef3c7; color: #92400e; font-size: .8rem; }
.mb-connect__accounts { list-style: none; padding: 0; margin: 0 0 1rem; border: 1px solid #e5e7eb; border-radius: .5rem; }
.mb-connect__accounts li { display: flex; justify-content: space-between; gap: 1rem; padding: .55rem .75rem; border-top: 1px solid #e5e7eb; }
.mb-connect__accounts li:first-child { border-top: 0; }
.mb-connect__actions { display: flex; gap: .5rem; flex-wrap: wrap; }
.mb-connect__ok { margin-top: .75rem; color: #047857; }
.mb-connect__error { margin-top: .75rem; color: #b91c1c; }
</style>

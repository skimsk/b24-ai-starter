<script setup lang="ts">
import SplashBrandMark from '~/components/SplashBrandMark.vue'

/**
 * Шаг «Подключение банка»: клиент вставляет ключ API из личного кабинета
 * Модульбанка. Сервер проверяет ключ запросом счетов и сохраняет подключение.
 */
const emit = defineEmits<{
  (e: 'next'): void
}>()

const tochkaStore = useTochkaStore()

const apiToken = ref('')
const isConnecting = ref(false)
const showHelp = ref(false)
const error = ref('')

async function connectWith(opts: { apiToken?: string; sandbox?: boolean }) {
  error.value = ''
  isConnecting.value = true
  try {
    await tochkaStore.connect(opts)
    if (tochkaStore.status.connected) {
      apiToken.value = ''
      emit('next')
    } else {
      error.value = 'Модульбанк не подтвердил подключение. Попробуйте ещё раз.'
    }
  } catch {
    error.value = tochkaStore.error || 'Не удалось подключить Модульбанк'
  } finally {
    isConnecting.value = false
  }
}

function handleConnect() {
  const token = apiToken.value.trim()
  if (!token) {
    error.value = 'Вставьте ключ API из личного кабинета Модульбанка'
    return
  }
  connectWith({ apiToken: token })
}

function handleSandbox() {
  connectWith({ sandbox: true })
}
</script>

<template>
  <section class="setup-connect">
    <div class="setup-connect__panel">
      <div class="setup-connect__logo">
        <div class="setup-connect__logo-ring">
          <div
            v-if="isConnecting"
            class="setup-connect__logo-spinner"
            aria-hidden="true"
          />
          <SplashBrandMark compact />
        </div>
      </div>

      <h1 class="setup-connect__title">Подключение Модульбанка</h1>

      <p class="setup-connect__text">
        Вставьте ключ API из личного кабинета Модульбанка
      </p>

      <form class="setup-connect__form" @submit.prevent="handleConnect">
        <input
          v-model="apiToken"
          class="setup-connect__input"
          type="password"
          autocomplete="off"
          placeholder="Ключ API Модульбанка"
          :disabled="isConnecting"
        >
        <div class="setup-connect__actions">
          <button
            type="submit"
            class="setup-connect__btn setup-connect__btn--primary"
            :disabled="isConnecting || !apiToken.trim()"
          >
            {{ isConnecting ? 'Проверяю ключ...' : 'Подключить Модульбанк' }}
          </button>
        </div>
      </form>

      <p v-if="error" class="setup-connect__error">
        {{ error }}
      </p>

      <p class="setup-connect__hint">
        <button type="button" class="setup-connect__link" @click="showHelp = !showHelp">
          Где взять ключ API?
        </button>
        ·
        <button type="button" class="setup-connect__link" :disabled="isConnecting" @click="handleSandbox">
          Попробовать на тестовых данных
        </button>
      </p>

      <ol v-if="showHelp" class="setup-connect__steps">
        <li>Войдите в личный кабинет Модульбанка с компьютера.</li>
        <li>Откройте «Настройки» → «API» (раздел для интеграций).</li>
        <li>Создайте ключ с правами «account-info» и «operation-history».</li>
        <li>Скопируйте ключ и вставьте его в поле выше.</li>
      </ol>
      <p v-if="showHelp" class="setup-connect__hint">
        Ключ даёт только просмотр счетов и выписки, платежи по нему сделать нельзя.
        Отозвать его можно в личном кабинете в любой момент.
      </p>
    </div>
  </section>
</template>

<style scoped>
.setup-connect {
  display: block;
  width: 100%;
  box-sizing: border-box;
  padding: 4rem 1rem;
  min-height: 500px;
}

.setup-connect__panel {
  display: block;
  width: 560px;
  max-width: 100%;
  margin: 0 auto;
  text-align: center;
  box-sizing: border-box;
}

.setup-connect__logo {
  display: block;
  width: 100%;
  margin-bottom: 1.25rem;
}

.setup-connect__logo-ring {
  position: relative;
  display: inline-block;
}

.setup-connect__logo-spinner {
  position: absolute;
  inset: -4px;
  border: 2px solid #e5e7eb;
  border-top-color: var(--mb-accent);
  border-radius: 1.35rem;
  animation: setup-connect-spin 0.8s linear infinite;
  pointer-events: none;
}

.setup-connect__title,
.setup-connect__text,
.setup-connect__error,
.setup-connect__hint {
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin-left: auto;
  margin-right: auto;
  white-space: normal;
  word-break: normal;
  overflow-wrap: normal;
}

.setup-connect__title {
  font-size: 1.25rem;
  font-weight: 700;
  color: #111827;
  margin-bottom: 0.5rem;
  line-height: 1.4;
}

.setup-connect__text {
  font-size: 0.875rem;
  color: #6b7280;
  line-height: 1.6;
  margin-bottom: 2rem;
}

.setup-connect__error {
  font-size: 0.875rem;
  color: #dc2626;
  background: #fef2f2;
  border-radius: 0.75rem;
  padding: 0.75rem 1.25rem;
  line-height: 1.6;
  margin-bottom: 1.5rem;
  text-align: center;
}

.setup-connect__actions {
  display: flex;
  justify-content: center;
  width: 100%;
  margin-bottom: 0.5rem;
}

.setup-connect__btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0.625rem 2rem;
  font-size: 0.875rem;
  font-weight: 500;
  border-radius: 0.75rem;
  border: none;
  cursor: pointer;
  white-space: nowrap;
  transition: background-color 0.15s ease, opacity 0.15s ease;
}

.setup-connect__btn--primary {
  background: var(--mb-primary);
  color: #fff;
}

.setup-connect__btn--primary:hover:not(:disabled) {
  background: var(--mb-primary-hover);
}

.setup-connect__btn--primary:disabled {
  background: var(--mb-accent);
  opacity: 0.45;
  cursor: not-allowed;
}

.setup-connect__btn--secondary {
  background: #fff;
  color: #374151;
  border: 1px solid #e5e7eb;
}

.setup-connect__btn--secondary:hover {
  background: #f9fafb;
}

.setup-connect__hint {
  font-size: 0.75rem;
  color: #9ca3af;
  line-height: 1.6;
  margin-top: 2rem;
}

.setup-connect__form {
  display: block;
  width: 100%;
  margin-top: 1.25rem;
}

.setup-connect__input {
  display: block;
  width: 100%;
  box-sizing: border-box;
  margin-bottom: 0.75rem;
  padding: 0.7rem 0.9rem;
  border: 1px solid #d1d5db;
  border-radius: 0.75rem;
  font: inherit;
  font-size: 0.9rem;
}

.setup-connect__input:focus {
  outline: none;
  border-color: var(--mb-accent);
  box-shadow: 0 0 0 3px var(--mb-soft);
}

.setup-connect__link {
  padding: 0;
  border: 0;
  background: none;
  color: var(--mb-accent);
  font: inherit;
  cursor: pointer;
}

.setup-connect__link:disabled {
  opacity: 0.5;
  cursor: default;
}

.setup-connect__steps {
  margin: 0.75rem auto 0;
  padding-left: 1.25rem;
  max-width: 26rem;
  text-align: left;
  color: #374151;
  font-size: 0.875rem;
  line-height: 1.6;
}

@keyframes setup-connect-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>

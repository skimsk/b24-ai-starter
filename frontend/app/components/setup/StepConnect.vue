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
          {{ showHelp ? 'Скрыть подсказку' : 'Где взять ключ API?' }}
        </button>
        ·
        <button type="button" class="setup-connect__link" :disabled="isConnecting" @click="handleSandbox">
          Попробовать на тестовых данных
        </button>
      </p>

      <div v-if="showHelp" class="mb-help" role="region" aria-label="Как получить ключ API Модульбанка">
        <div class="mb-help__head">
          <span class="mb-help__icon" aria-hidden="true">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
              <circle cx="8" cy="15" r="4" /><path d="M10.8 12.2 20 3M17 6l3 3M15 8l2 2" />
            </svg>
          </span>
          <div>
            <div class="mb-help__title">Как получить ключ API</div>
            <div class="mb-help__subtitle">Займёт около минуты в личном кабинете банка</div>
          </div>
        </div>

        <ol class="mb-help__steps">
          <li class="mb-help__step">
            <span class="mb-help__num">1</span>
            <div>
              Войдите в <a href="https://my.modulbank.ru" target="_blank" rel="noopener" class="mb-help__a">личный кабинет Модульбанка</a> с компьютера.
            </div>
          </li>
          <li class="mb-help__step">
            <span class="mb-help__num">2</span>
            <div>
              В верхнем меню откройте
              <span class="mb-help__path"><span>Ещё</span><span class="mb-help__sep">›</span><span>Прочее</span><span class="mb-help__sep">›</span><span>API банка</span></span>
            </div>
          </li>
          <li class="mb-help__step">
            <span class="mb-help__num">3</span>
            <div>
              В окне «Подключение к API» отметьте права:
              <ul class="mb-help__scopes">
                <li><span class="mb-help__check mb-help__check--on">✓</span><code>account-info</code><span class="mb-help__muted">компании и счета</span></li>
                <li><span class="mb-help__check mb-help__check--on">✓</span><code>operation-history</code><span class="mb-help__muted">история операций</span></li>
                <li><span class="mb-help__check">–</span><code>operation-upload</code><span class="mb-help__muted">не нужен</span></li>
              </ul>
            </div>
          </li>
          <li class="mb-help__step">
            <span class="mb-help__num">4</span>
            <div>Нажмите «Сгенерировать», скопируйте токен и вставьте его в поле выше.</div>
          </li>
        </ol>

        <div class="mb-help__note">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M12 3 4 6v6c0 4.5 3.4 8.3 8 9 4.6-.7 8-4.5 8-9V6l-8-3Z" /><path d="m9 12 2 2 4-4" />
          </svg>
          <span>С этим ключом можно только смотреть счета и выписку: платить по нему нельзя. Отозвать ключ можно в том же разделе в любой момент.</span>
        </div>
      </div>
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

.mb-help {
  margin: 1rem auto 0;
  max-width: 30rem;
  text-align: left;
  background: #fff;
  border: 1px solid var(--mb-soft-active);
  border-radius: 1rem;
  box-shadow: 0 4px 16px rgba(0, 34, 92, 0.06);
  overflow: hidden;
  animation: mb-help-in 0.18s ease-out;
}

.mb-help__head {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  padding: 0.9rem 1.1rem;
  background: var(--mb-soft);
}

.mb-help__icon {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  border-radius: 0.65rem;
  background: var(--mb-primary);
  color: #fff;
}

.mb-help__icon svg {
  width: 1.15rem;
  height: 1.15rem;
}

.mb-help__title {
  font-size: 0.95rem;
  font-weight: 700;
  color: var(--mb-primary);
}

.mb-help__subtitle {
  font-size: 0.75rem;
  color: #4b5563;
  margin-top: 0.1rem;
}

.mb-help__steps {
  list-style: none;
  margin: 0;
  padding: 0.5rem 1.1rem 0.25rem;
}

.mb-help__step {
  display: flex;
  gap: 0.75rem;
  padding: 0.6rem 0;
  font-size: 0.85rem;
  line-height: 1.55;
  color: #1f2937;
}

.mb-help__step + .mb-help__step {
  border-top: 1px dashed #e5e7eb;
}

.mb-help__num {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.5rem;
  height: 1.5rem;
  margin-top: 0.05rem;
  border-radius: 999px;
  background: var(--mb-accent);
  color: #fff;
  font-size: 0.75rem;
  font-weight: 700;
}

.mb-help__a {
  color: var(--mb-accent);
  font-weight: 500;
  text-decoration: none;
}

.mb-help__a:hover {
  text-decoration: underline;
}

.mb-help__path {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.3rem;
  margin-top: 0.3rem;
}

.mb-help__path > span:not(.mb-help__sep) {
  padding: 0.1rem 0.5rem;
  border-radius: 0.4rem;
  background: var(--mb-soft);
  color: var(--mb-primary);
  font-weight: 600;
  font-size: 0.8rem;
}

.mb-help__sep {
  color: #9ca3af;
}

.mb-help__scopes {
  list-style: none;
  margin: 0.4rem 0 0;
  padding: 0;
}

.mb-help__scopes li {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.15rem 0;
}

.mb-help__scopes code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 0.8rem;
  color: #111827;
}

.mb-help__check {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1rem;
  height: 1rem;
  border-radius: 0.25rem;
  border: 1px solid #d1d5db;
  color: #9ca3af;
  font-size: 0.7rem;
  line-height: 1;
}

.mb-help__check--on {
  border-color: var(--mb-lime);
  background: var(--mb-lime);
  color: #fff;
  font-weight: 700;
}

.mb-help__muted {
  color: #6b7280;
  font-size: 0.78rem;
}

.mb-help__note {
  display: flex;
  gap: 0.6rem;
  margin: 0.25rem 1.1rem 1rem;
  padding: 0.7rem 0.8rem;
  border-radius: 0.75rem;
  background: #f3f9ec;
  color: #365314;
  font-size: 0.78rem;
  line-height: 1.5;
}

.mb-help__note svg {
  flex: none;
  width: 1.1rem;
  height: 1.1rem;
  color: #5eb900;
  margin-top: 0.05rem;
}

@keyframes mb-help-in {
  from {
    opacity: 0;
    transform: translateY(-4px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

@keyframes setup-connect-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>

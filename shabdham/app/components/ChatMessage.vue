<template>
  <div class="chat-message" :class="[`chat-message--${role}`]">
    <div class="chat-message__bubble">
      <span class="chat-message__label">{{ role === 'user' ? 'USER' : 'AI' }}</span>
      <p>{{ text }}</p>
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  role: 'user' | 'assistant'
  text: string
}>()
</script>

<style scoped>
.chat-message {
  display: flex;
  width: 100%;
}

.chat-message--user {
  justify-content: flex-end;
}

.chat-message--assistant {
  justify-content: flex-start;
}

.chat-message__bubble {
  max-width: min(100%, 28rem);
  background: rgba(255, 255, 255, 0.68);
  border: 1px solid rgba(26, 26, 26, 0.08);
  border-radius: 1rem;
  padding: 0.85rem 1rem 0.9rem;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  box-shadow: 0 10px 30px rgba(20, 20, 20, 0.08);
}

.chat-message--user .chat-message__bubble {
  background: rgba(17, 17, 17, 0.96);
  color: #fff;
}

.chat-message__label {
  display: inline-block;
  font-size: 0.62rem;
  text-transform: uppercase;
  letter-spacing: 0.12em;
  opacity: 0.7;
  margin-bottom: 0.4rem;
}

.chat-message__bubble p {
  font-size: 0.94rem;
  line-height: 1.6;
  color: inherit;
  white-space: pre-wrap;
}
</style>

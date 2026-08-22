<script setup>
defineProps({ message: String, type: { type: String, default: 'success' } })
</script>

<template><transition name="toast"><div v-if="message" class="toast-message" :class="`toast-message--${type}`">{{ message }}</div></transition></template>


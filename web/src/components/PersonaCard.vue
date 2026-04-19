<script setup lang="ts">
import { computed } from "vue";
import Card from "@/components/ui/Card.vue";
import Avatar from "@/components/ui/Avatar.vue";
import Badge from "@/components/ui/Badge.vue";
import { resolveArchetype } from "@/lib/archetypes";
import type { AgentProfile } from "@/types/api";

interface Props {
  profile: AgentProfile;
}
const props = defineProps<Props>();

const name = computed(
  () => props.profile.realname || props.profile.name || props.profile.username || `Agent`,
);
const handle = computed(() => props.profile.username || props.profile.user_name || "");
const archetype = computed(() => resolveArchetype(props.profile.entity_type || props.profile.profession || ""));
const bio = computed(() => props.profile.bio || props.profile.persona || "");
</script>

<script lang="ts">
export default { inheritAttrs: false };
</script>

<template>
  <Card hoverable v-bind="$attrs" class="persona-card-clickable">
    <div class="head">
      <Avatar :name="name" :color="archetype.color" :size="40" />
      <div class="ident">
        <div class="name">{{ name }}</div>
        <div v-if="handle" class="handle">@{{ handle }}</div>
      </div>
      <Badge :color="archetype.color">{{ archetype.label }}</Badge>
    </div>
    <p v-if="bio" class="bio">{{ bio }}</p>
  </Card>
</template>

<style scoped>
.head {
  display: flex;
  align-items: center;
  gap: var(--gap-sm);
}
.ident {
  flex: 1;
  min-width: 0;
}
.name {
  font-size: 14px;
  font-weight: 600;
  color: var(--fg-strong);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.handle {
  font-size: 11px;
  color: var(--fg-muted);
  margin-top: 1px;
}
.bio {
  margin: var(--gap-sm) 0 0 0;
  font-size: 12px;
  line-height: 1.5;
  color: var(--fg-muted);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.persona-card-clickable { cursor: pointer; }
</style>

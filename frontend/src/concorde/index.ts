// Único punto de entrada de Concorde en el frontend: las rutas importan de "@/concorde", nunca de
// "@/concorde/components/*". Los archivos de components/ y styles/ se instalan TAL CUAL desde el
// registry (https://concorde-v2-theta.vercel.app/r/<nombre>.json, AaronCoorahua/ConcordeV2 master
// @ 50ab6c3, 2026-11-20): no se editan; si falta algo se cambia en Concorde y se reinstala.
export { default as Button, UserIcon } from "./components/Button";
export type { ButtonProps, ButtonVariant } from "./components/Button";
export { default as AvatarZone } from "./components/AvatarZone";
export { ChatBubble } from "./components/ChatBubble";
export { StatusTag } from "./components/StatusTag";
export type { StatusTone } from "./components/StatusTag";

---
name: Subastín — Panel de Asesor
description: Cockpit operativo de VMC para triar, tomar y responder conversaciones derivadas por la IA
colors:
  vault-violet: "#8460E5"
  vault-violet-light: "#AE8EFF"
  vault-violet-deep: "#3B1782"
  vault-violet-abyss: "#22005C"
  signal-orange: "#ED8936"
  signal-orange-light: "#FBC47D"
  signal-orange-deep: "#D46E20"
  confirm-teal: "#00AEB1"
  confirm-teal-deep: "#009095"
  ink: "#191C1C"
  paper: "#F7F7FB"
  surface-white: "#FFFFFF"
  muted: "#99A1AF"
  disabled-surface: "#E1E3E2"
typography:
  display:
    fontFamily: "'Plus Jakarta Sans', -apple-system, sans-serif"
    fontSize: "1.875rem"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "normal"
  body:
    fontFamily: "'Plus Jakarta Sans', -apple-system, sans-serif"
    fontSize: "0.875rem"
    fontWeight: 500
    lineHeight: 1.4
    letterSpacing: "normal"
  label:
    fontFamily: "'Plus Jakarta Sans', -apple-system, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 700
    lineHeight: 1.3
    letterSpacing: "0.04em"
rounded:
  full: "9999px"
  lg: "16px"
  sm: "8px"
spacing:
  xs: "4px"
  sm: "8px"
  md: "12px"
  lg: "16px"
  xl: "24px"
components:
  button-primary:
    backgroundColor: "{colors.signal-orange}"
    textColor: "{colors.surface-white}"
    rounded: "{rounded.full}"
    padding: "0 56px"
    height: "48px"
  button-secondary:
    backgroundColor: "{colors.vault-violet}"
    textColor: "{colors.surface-white}"
    rounded: "{rounded.full}"
    padding: "0 56px"
    height: "48px"
  status-pending-advisor:
    backgroundColor: "#FDF0E4"
    textColor: "#9A4A0F"
    rounded: "{rounded.full}"
  status-in-attention:
    backgroundColor: "#E3F8F8"
    textColor: "#00696B"
    rounded: "{rounded.full}"
  status-bot-attending:
    backgroundColor: "#F1EDFD"
    textColor: "{colors.vault-violet-deep}"
    rounded: "{rounded.full}"
  status-closed:
    backgroundColor: "#EEEEEE"
    textColor: "#5C6266"
    rounded: "{rounded.full}"
  card:
    backgroundColor: "{colors.surface-white}"
    rounded: "{rounded.lg}"
    padding: "20px"
  input:
    backgroundColor: "{colors.surface-white}"
    textColor: "{colors.ink}"
    rounded: "{rounded.lg}"
    height: "48px"
---

# Design System: Subastín — Panel de Asesor

## Overview

**Creative North Star: "The Control Tower"**

El panel es el centro de control donde un asesor humano toma el relevo cuando la IA no puede
resolver sola. El violeta profundo ("vault") es el panel nocturno siempre encendido; el naranja y
el teal son las luces de estado que dicen, sin necesidad de leer texto, qué necesita atención
ahora y qué ya está bajo control. Los botones no son rectángulos planos: llevan un brillo interno
(highlight superior) y un halo de color a su alrededor, como un interruptor iluminado de consola —
el sistema *se siente* encendido, no solo dibujado.

Se rechaza explícitamente el look de dashboard SaaS genérico: nada de azul corporativo, nada de
tarjetas con ícono+título+texto todas idénticas sin jerarquía, nada de sombra negra plana. Cada
superficie de contenido es sobria (blanco, esquina de 16px, sombra ambiental con tinte violeta),
y toda la personalidad vive en los controles — botones, badges, focus rings — no en decoración de
fondo.

**Key Characteristics:**
- Violeta = identidad y acción primaria. Nunca se usa para decir "esto es urgente" — eso es
  trabajo del naranja.
- Tres colores de estado (naranja / teal / violeta claro) + un neutro, nunca un cuarto color de
  estado inventado.
- Todo control (botón, pestaña, badge, avatar) es completamente redondeado; todo contenedor de
  contenido (card, tabla, input) usa 16px u 8px — nunca full.
- La sombra por defecto es plana y neutra; el color en la sombra aparece solo cuando algo es
  interactivo — la profundidad comunica "esto responde", no decoración ambiental.

## Colors

Paleta de tres acentos sobre una base neutra fría — cada acento tiene un rol fijo, nunca
intercambiable.

### Primary
- **Vault Violet** (`#8460E5`): identidad de marca y acción primaria/secundaria (botones, tabs
  activos, focus ring por defecto, header de tabla). Es el color que dice "Subastín", no un
  estado del sistema.
- **Vault Violet Deep** (`#3B1782`): texto sobre fondos violeta claro, extremo oscuro de los
  gradientes de botón secundario y del header de tabla.
- **Vault Violet Light** (`#AE8EFF`): extremo claro de gradientes, estado hover.

### Secondary
- **Signal Orange** (`#ED8936`): "esto necesita al asesor ahora" — estado `PENDING_ADVISOR`,
  contador de no leídos, aviso de caso sin tomar, mitad del gradiente del botón primario.
- **Signal Orange Deep** (`#D46E20`): estado pressed/active de controles naranja.

### Tertiary
- **Confirm Teal** (`#00AEB1`): "esto ya está bajo control" — estado `IN_ATTENTION`, botón
  "negotiable". El único acento que comunica calma en vez de urgencia.

### Neutral
- **Ink** (`#191C1C`): texto principal sobre blanco.
- **Paper** (`#F7F7FB`): fondo de página — nunca blanco puro, para que las cards blancas destaquen.
- **Surface White** (`#FFFFFF`): fondo de cards, tabla, panel de contexto.
- **Muted** (`#99A1AF`): texto secundario, placeholders, estados deshabilitados.
- **Disabled Surface** (`#E1E3E2`): fondo de controles deshabilitados.

### Named Rules
**The Signal Color Rule.** Naranja = necesita al asesor ahora. Teal = ya está resuelto o en buenas
manos. Violeta = identidad y acción, nunca estado. Si un color nuevo parece necesario para un
estado, la respuesta correcta es revisar si realmente es uno de estos tres, no añadir un cuarto.

## Typography

**Display/Body/Label Font:** Plus Jakarta Sans (con `-apple-system, sans-serif` de respaldo)

**Character:** Una sola familia para todo el sistema — geométrica, cálida, sin serifas. El
registro cambia por peso y tamaño, nunca por familia.

### Hierarchy
- **Display** (700, 1.5rem/24px, 1.3): títulos de pantalla (`Dashboard operativo`, título de
  login). Aparece una vez por vista, nunca repetido.
- **Body** (500, 0.875rem/14px, 1.4): el peso por defecto de casi todo — mensajes, filas de
  tabla, texto de párrafo.
- **Label** (700, 0.6875rem/11px, 1.3, tracking 0.04em, mayúsculas): encabezados de tabla,
  etiquetas de stat card, badges de estado. Siempre en mayúsculas, siempre bold, nunca en tamaño
  de lectura.

### Named Rules
**The One Face Rule.** Plus Jakarta Sans lleva cada voz del producto — título, cuerpo y etiqueta.
Ningún componente nuevo introduce una segunda familia tipográfica, ni siquiera para "sentirse
técnico" (para eso está el color de estado, no una fuente mono).

## Layout

Densidad de herramienta de trabajo, no de landing: gaps ajustados dentro de un mismo grupo (4–8px),
separación generosa entre secciones (16–24px). El cockpit de la bandeja usa un modelo de columnas
persistentes (rail de cola + panel central + panel de contexto en desktop, lg: ≥1024px) que colapsa
a una sola columna en mobile — nunca dos columnas apretadas en pantalla angosta.

El dashboard es **una sola columna, de arriba a abajo** (señales vitales → volumen → distribución
→ actividad reciente): se probó un layout de contenido + rail lateral fijo (`grid-cols-[1fr_300px]`
con `lg:sticky`) y resultó confuso — el escaneo vertical simple es lo que de verdad es fácil de
usar en este panel. Cada sección es una card a todo el ancho; no se fuerza una composición de
columnas donde el contenido no la pide. Login es de una sola columna centrada.

### Named Rules
**The Boring Scan Rule.** Este dashboard prioriza el escaneo vertical obvio sobre una composición
más "interesante". Una repetición ocasional de un número (la misma cuenta en una card y en la
leyenda de distribución) es aceptable si la alternativa es un layout menos familiar.

## Elevation & Depth

Sistema híbrido: las superficies de contenido en reposo son planas con una sombra ambiental sutil
con tinte violeta (`rgba(32,0,104,0.06) 0 1px 2px, rgba(32,0,104,0.10) 0 12px 32px` en la tabla;
`shadow-sm` de Tailwind en cards). El color entra en la sombra solo cuando el elemento es
interactivo: los botones llevan un halo de color detrás (`filter: blur(14–18px)`) que se
intensifica en hover, más un highlight interno translúcido arriba — como luz saliendo del propio
control, no una sombra que cae sobre él.

### Shadow Vocabulary
- **Ambient card** (`shadow-sm` / `rgba(32,0,104,0.06) 0 1px 2px, rgba(32,0,104,0.10) 0 12px 32px`):
  reposo de cualquier card, panel o tabla.
- **Button glow** (`rgba(<accent>,0.3–0.4) 0 8px 24px` + blur externo 14–18px del mismo color del
  gradiente): halo detrás de cualquier botón, se intensifica en hover.
- **Focus halo** (`0 0 0 2px white, 0 0 0 5px <accent>`): doble anillo blanco+color en foco por
  teclado, consistente en todos los controles.

### Named Rules
**The Glow-Is-Signal Rule.** Una sombra de color solo existe sobre un control interactivo, teñida
de su propio acento. Un card o panel nunca lleva sombra de color — su sombra siempre es la
ambiental neutra con tinte violeta muy sutil.

## Shapes

**The Pill Rule.** Todo lo que es un control (botón, pestaña, badge de estado, avatar, chip de
pulso) es `border-radius: 9999px` — completamente redondeado. Todo lo que contiene contenido
(card, panel, input, tabla) usa 16px, salvo la tabla misma que usa 8px por ser una superficie más
densa y tabular. Nunca un radio intermedio (6px, 12px) fuera de estos dos valores.

## Components

### Buttons
- **Shape:** completamente redondeado (`{rounded.full}`), alto fijo 48px (40px en variantes `sm`).
- **Primary:** gradiente naranja→violeta (`#ED8936` → `#8460E5`), borde gradiente sutil, texto
  blanco con sombra, halo naranja/violeta detrás. La acción principal de una pantalla.
- **Secondary:** gradiente violeta claro→oscuro (`#8460E5` → `#3B1782`). Acción secundaria fuerte
  (ej. "Tomar conversación").
- **Negotiable:** gradiente teal→violeta (`#00AEB1` → `#8460E5`), 200px mínimo. Reservado para
  acciones de negociación del dominio de subastas.
- **Outline:** relleno transparente, borde gradiente naranja 1px, texto naranja — invitación de
  baja presión a escala completa (48px), para una pantalla con poco más alrededor (ej. "Ver" en
  la tabla del dashboard).
- **Ghost:** borde blanco translúcido sobre fondos oscuros/de color.
- **Quiet header action (patrón nuevo, no es un componente Concorde):** los 48px/40px de la
  familia `Button` son demasiado pesados dentro de una fila de header ya ocupada (avatar +
  nombre + badge). Pill pequeña (px-3 py-1.5, ~32px), borde `neutral-200`, texto `neutral-500`,
  hover oscurece borde y texto — mismo lenguaje que el botón de adjuntar imagen del footer del
  hilo. Usar para una acción secundaria y poco frecuente que vive dentro de un header ya denso
  (ej. "Cerrar caso"), nunca como reemplazo general de `outline`.
- **Hover/Focus:** todas las variantes suben 2px y escalan a 1.02 en hover; el foco por teclado
  siempre es el doble anillo blanco+color del halo.

### Chips (Compact Filter Chips — patrón nuevo, cockpit)
Para grupos de filtro que no caben en el `TabSelector` completo (que impone 83px mínimos por
pestaña): pill de fondo transparente, texto violeta; activo = relleno degradado violeta claro→
oscuro + texto blanco. Cuando el número de opciones es fijo (4, como los estados de conversación),
usar grid de N columnas iguales — garantiza una sola fila sin envolver ni pedir scroll; el texto
trunca con "…" solo en el caso extremo de una pantalla diminuta, nunca desaparece sin aviso. Usar
este patrón, no forzar `TabSelector`, en cualquier contenedor angosto (rail, sidebar, drawer).

### Status Badges
- **Style:** pill pequeña (11px, bold, mayúsculas), fondo al 10–12% de opacidad del color de
  estado, texto en la versión oscura del mismo color, punto sólido del color puro a la izquierda.
- **State:** 4 variantes fijas — `PENDING_ADVISOR` (naranja), `IN_ATTENTION` (teal),
  `BOT_ATTENDING` (violeta claro), `CLOSED` (gris). Nunca una quinta.

### Cards / Containers
- **Corner Style:** 16px (`rounded-2xl`).
- **Background:** blanco puro sobre fondo de página `#F7F7FB`.
- **Shadow Strategy:** ambient card (ver Elevation).
- **Internal Padding:** 20px (`p-5`) en cards de contenido; 12px (`p-3`) en contenedores densos
  como el rail de la cola.

### Inputs / Fields
- **Style:** 16px de radio, borde gradiente violeta→crema 1px en reposo.
- **Focus:** borde 2px con gradiente naranja→violeta + sombra de glow naranja sutil.
- **Error:** borde magenta sólido 1px (`#8E0B82`, peligro/atención), sin gradiente, mensaje
  magenta debajo.

### Navigation
- Header con marca + tabs de navegación en pill (activo = fondo violeta al 10% + texto violeta
  oscuro), sin sidebar fija. En mobile los labels de texto se esconden y solo quedan los íconos
  (`hidden sm:inline`).

### Avatar (AvatarZone)
Círculo con gradiente naranja diagonal (`#FF9639` → `#EF852E` → `#BE3D00`) y silueta blanca — el
placeholder universal para cualquier usuario sin foto (que es el 100% de los casos hoy).

### Message Bubble
Burbuja de chat: mensaje del asesor = relleno violeta sólido + texto blanco; mensaje del bot =
gris neutro claro; mensaje del usuario = blanco con sombra ambiental. Eventos de sistema (tomar,
cerrar ticket) son una pill gris centrada, sin burbuja — nunca se confunden con un mensaje real.

### Alert Card (peligro / llamado de atención)
Excepción deliberada a la paleta de 3 acentos (`.alert-card` en `globals.css`): fill degradado
vault→magenta→rosa (`linear-gradient(90deg, vault-500 0%, #cc00ff 55%, #ff0066 100%)`) sin ningún
tramo claro de por medio, borde degradado a juego y `text-shadow` para legibilidad — texto siempre
blanco. Es el mismo tratamiento de `.alert-card` en el Centro de Ayuda de VMC
(`CentroDeAyudaVMC/src/styles/global.css`): mantiene el magenta como el color compartido de
"peligro/atención" en toda la marca VMC, no una elección local. El error de `Input` (ver
Inputs/Fields) usa la misma familia magenta — una versión oscura para texto/borde sobre blanco —
así que ambos ("aviso lleno" y "borde de campo") hablan el mismo idioma de peligro. No cuenta
contra **The Signal Color Rule**: esa regla gobierna los 3 acentos de *estado de conversación*,
no los avisos puntuales de peligro.

## Do's and Don'ts

### Do:
- **Do** usar los tres acentos (naranja/teal/violeta) solo con su rol fijo — naranja urgencia,
  teal resuelto, violeta identidad — en cualquier componente nuevo.
- **Do** usar la sombra ambiental con tinte violeta (`rgba(32,0,104,...)`) en cualquier card o
  panel nuevo, nunca una sombra negra genérica.
- **Do** mantener Plus Jakarta Sans como única familia; cambiar solo peso/tamaño para jerarquía.
- **Do** usar radio completo en controles y 16px/8px en contenedores — nunca un radio intermedio.
- **Do** envolver en vez de recortar cuando un grupo de controles no cabe en su contenedor (ver
  Compact Filter Chips) — nunca esconder contenido sin aviso visual.

### Don't:
- **Don't** introducir un azul corporativo genérico ni un quinto color de estado.
- **Don't** usar emoji o glifos unicode como ícono — hay un set propio en `components/icons.tsx`
  (stroke 1.6, currentColor).
- **Don't** poner sombra de color en un card o panel — el color de sombra es exclusivo de
  controles interactivos.
- **Don't** usar `TabSelector` en un contenedor más angosto que ~360px con 3+ opciones; usar el
  patrón de Compact Filter Chips en su lugar.
- **Don't** decorar con gradientes fuera de botones y avatar — el resto del sistema es plano por
  diseño, para que el gradiente siga significando "esto es un control".

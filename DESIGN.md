# DESIGN.md — UI Design Tokens & Dashboard Rules

## Color Palette

| Token | Value | Usage |
|-------|-------|-------|
| `bg-primary` | `#111111` | Page background |
| `bg-card` | `#1f2937` | Card/panel backgrounds |
| `bg-input` | `#374151` | Input fields, code blocks |
| `accent` | `#4CAF50` | Primary action color, links, badges for BOT_ACTIVE |
| `accent-hover` | `#66BB6A` | Hover state for accent buttons |
| `warning` | `#F59E0B` | Pending approval badges |
| `danger` | `#EF4444` | Error banners, HUMAN_ONLY badges |
| `text-primary` | `#EEEEEE` | Main text |
| `text-muted` | `#9CA3AF` | Secondary/muted text |

## Typography

- **Font family**: `system-ui` (no custom fonts)
- **Base size**: 16px (Tailwind default)
- **Headings**: bold, `text-xl` / `text-2xl`
- **Monospace**: for code/IDs in backtick elements

## Layout

### Dashboard Structure
```
┌──────────────────────────────────────────────────┐
│ Header: "Hermes WhatsApp Gateway" + Health Badge │
├────────────┬─────────────────────────────────────┤
│            │                                     │
│ Sidebar    │  Chat Panel                         │
│ (280px)    │  ┌─────────────────────────────┐    │
│            │  │ Conversation header          │    │
│ Conv List  │  │ + State Toggle               │    │
│            │  ├─────────────────────────────┤    │
│ - phone    │  │                              │    │
│ - state    │  │ Message thread               │    │
│ - unread   │  │ (inbound/outbound交替)       │    │
│ - preview  │  │                              │    │
│            │  ├─────────────────────────────┤    │
│            │  │ Message Input                │    │
│            │  │ (human reply, send button)   │    │
│            │  └─────────────────────────────┘    │
│            │                                     │
│            │  Agent Editor (collapsible)         │
│            │  ┌─────────────────────────────┐    │
│            │  │ System Prompt               │    │
│            │  │ Escalation Marker            │    │
│            │  │ Fallback Responses (JSON)    │    │
│            │  │ Save / Activate              │    │
│            │  └─────────────────────────────┘    │
├────────────┴─────────────────────────────────────┤
│ Error Banner (if active)                          │
│ Notification Banner (toast)                       │
└──────────────────────────────────────────────────┘
```

## State Badges

| State | Color | Label |
|-------|-------|-------|
| `BOT_ACTIVE` | `#4CAF50` (accent) | "Bot Activo" |
| `PENDING_APPROVAL` | `#F59E0B` (warning) | "Pendiente" |
| `HUMAN_ONLY` | `#EF4444` (danger) | "Humano" |

## Components

| Component | File | Purpose |
|-----------|------|---------|
| `ConversationList` | `dashboard/components/ConversationList.tsx` | Sidebar: phone, state badge, last message preview, unread count |
| `ChatPanel` | `dashboard/components/ChatPanel.tsx` | Main area: message thread with sender badges, timestamps |
| `StateToggle` | `dashboard/components/StateToggle.tsx` | Dropdown/buttons to change conversation state |
| `MessageInput` | `dashboard/components/MessageInput.tsx` | Text input + send button for human replies |
| `AgentEditor` | `dashboard/components/AgentEditor.tsx` | Form: system prompt (textarea), escalation marker, fallback JSON, save/activate |
| `ErrorBanner` | `dashboard/components/ErrorBanner.tsx` | Full-width red banner for critical errors |
| `NotificationBanner` | `dashboard/components/NotificationBanner.tsx` | Auto-dismiss toast for escalations and events |

## WebSocket Protocol

Dashboard connects to `ws://localhost:8080/ws?token=<DASHBOARD_TOKEN>`.

### Server → Client events

| Event type | Payload | When |
|------------|---------|------|
| `new-message` | phone, message, direction, source, state | Every inbound/outbound message |
| `bot-replied` | phone, response, message_id, decision | Bot sends a reply |
| `escalated` | phone, reason, sentiment, decision | Conversation escalated |
| `waiting-for-human` | phone | Message arrived in HUMAN_ONLY conversation |
| `error` | phone, error | Processing error |

### Client → Server events

| Event type | Payload | When |
|------------|---------|------|
| `ping` | — | Keep-alive |

### Reconnection

Exponential backoff: 1s → 2s → 4s → 8s → max 30s. Implemented in `dashboard/hooks/useWebSocket.ts`.

## Iconography

- **lucide-react** icon library
- Key icons: `MessageSquare` (messages), `Bot` (bot state), `User` (human state), `AlertTriangle` (escalation), `Send` (send button), `RefreshCw` (reload)

## Responsive

- Dashboard is optimized for desktop (1280px+).
- Sidebar collapses on mobile (not currently implemented — desktop-only for operators).

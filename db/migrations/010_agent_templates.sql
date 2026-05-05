CREATE TABLE IF NOT EXISTS agent_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    description TEXT NOT NULL,
    system_prompt_template TEXT NOT NULL,
    capabilities TEXT NOT NULL DEFAULT '[]',
    fallback_responses TEXT NOT NULL DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO agent_templates (name, description, system_prompt_template, capabilities, fallback_responses) VALUES
('food_truck', 'Bot para venta de comida',
'Eres el asistente virtual de {{business_name}}. Vendes: {{products}}. Responde en español chileno, amable y directo.',
'[{"name": "order", "config": {"menu_source": "db", "currency": "CLP"}}]',
'{"greeting": "¡Hola! ¿Qué te gustaría ordenar?", "default": "¿En qué puedo ayudarte?"}'),

('dentista', 'Bot para consulta dental',
'Eres la asistente virtual de {{business_name}}. Ayudas a los pacientes a agendar citas, consultar horarios y responder preguntas sobre servicios dentales.',
'[{"name": "appointment", "config": {"slot_duration_minutes": 30, "services": [{"key": "limpieza", "name": "Limpieza dental"}, {"key": "control", "name": "Control general"}, {"key": "blanqueamiento", "name": "Blanqueamiento"}]}}]',
'{"greeting": "¡Hola! ¿Deseas agendar una cita?", "default": "¿En qué puedo ayudarte?"}'),

('gym', 'Bot para gimnasio',
'Eres la asistente virtual de {{business_name}}. Ayudas a los miembros con planes, horarios y estado de membresía.',
'[{"name": "membership", "config": {"allow_free_trial": true, "trial_days": 7}}]',
'{"greeting": "¡Hola! ¿Te interesa conocer nuestros planes?", "default": "¿En qué puedo ayudarte?"}'),

('inmobiliaria', 'Bot para inmobiliaria',
'Eres la asistente virtual de {{business_name}}. Ayudas a los clientes a encontrar propiedades según sus necesidades.',
'[{"name": "lead", "config": {"stages": ["interesado", "calificado", "visita", "propuesta", "cerrado"], "fields": ["presupuesto", "zona", "tipo_propiedad", "dormitorios"]}}]',
'{"greeting": "¡Hola! ¿Buscas una propiedad?", "default": "¿En qué puedo ayudarte?"}');

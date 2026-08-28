from __future__ import annotations

import json

from .models import BrandContext


class PromptBuilder:
    @staticmethod
    def video_idea_prompt(context: BrandContext, style: str) -> str:
        audience = ", ".join(context.audience)
        return f"""
Eres estratega creativo para contenido de redes de ConectaProIA.
Responde SOLO JSON valido.

Marca: {context.company_name}
Tagline: {context.tagline}
Mision: {context.mission}
Audiencia: {audience}
Mensajes clave: {', '.join(context.key_messages)}
CTA oficial: {context.call_to_action}
Style objetivo: {style}

Genera una idea concreta para un reel de alto impacto.
JSON:
{{
  "idea": "string"
}}
""".strip()

    @staticmethod
    def video_script_prompt(
        context: BrandContext,
        topic: str,
        duration_seconds: int | None,
        sections: int,
        style: str,
        dialogue_seed: str | None = None,
    ) -> str:
        audience = ", ".join(context.audience)
        promises = ", ".join(context.brand_promises)
        key_messages = ", ".join(context.key_messages)
        safety = " ".join(context.legal_safety)
        seed_block = f"Dialogo base del usuario (usar como referencia): {dialogue_seed}" if dialogue_seed else ""
        duration_instruction = (
            f"Duracion orientativa: {duration_seconds} segundos (sin sacrificar calidad narrativa)."
            if duration_seconds
            else "Sin limite fijo de segundos: prioriza historia completa, coherente y persuasiva."
        )

        if style == "dialogo":
            return f"""
Eres director creativo y guionista senior de reels verticales para ConectaProIA.
Responde SOLO JSON valido, sin markdown.

Contexto de marca:
- Empresa: {context.company_name}
- Tagline: {context.tagline}
- Mision: {context.mission}
- Audiencia: {audience}
- Promesas: {promises}
- Mensajes clave: {key_messages}
- Alcance: {context.service_scope}
- CTA oficial: {context.call_to_action}
- Seguridad legal: {safety}

Objetivo:
Crear REEL de DIALOGO entre 2 personas sobre: {topic}
{duration_instruction}
Secciones visuales requeridas: {sections}
{seed_block}

JSON esperado:
{{
  "style": "dialogo",
  "hook": "string",
  "dialogue": [
    {{ "speaker": "Usuario", "line": "string" }},
    {{ "speaker": "Asesor ConectaProIA", "line": "string" }}
  ],
  "sections": [
    {{ "title": "string", "narration": "string", "onscreen_text": "string" }}
  ],
  "cta": "{context.call_to_action}"
}}

Reglas de calidad:
1) Entre 4 y 8 turnos de dialogo, alternando speakers.
2) Conversacion natural, directa, entusiasta y convincente.
3) Debe mencionar WhatsApp y profesionales verificados.
4) Evitar promesas absolutas.
5) Debe tener inicio (problema), desarrollo (solucion), cierre (accion). No escribir etiquetas dentro de lineas (ej: "Persona 1:").
6) Espanol neutro, sin acotaciones teatrales.
""".strip()

        return f"""
Eres estratega senior de contenido de ConectaProIA.
Responde SOLO JSON valido, sin markdown.

Contexto de marca:
- Empresa: {context.company_name}
- Tagline: {context.tagline}
- Mision: {context.mission}
- Audiencia: {audience}
- Promesas: {promises}
- Mensajes clave: {key_messages}
- Alcance: {context.service_scope}
- CTA oficial: {context.call_to_action}
- Seguridad legal: {safety}

Objetivo:
Crear REEL PUBLICITARIO vertical sobre: {topic}
{duration_instruction}
Secciones requeridas: {sections}
{seed_block}

JSON esperado:
{{
  "style": "promo",
  "hook": "string",
  "sections": [
    {{
      "title": "string",
      "narration": "string",
      "onscreen_text": "string"
    }}
  ],
  "cta": "string"
}}

Reglas de calidad:
1) Gancho fuerte al inicio.
2) Lenguaje claro y profesional.
3) Sin promesas absolutas ni claims no verificables.
4) Secuencia narrativa completa: problema, solucion, beneficio, accion.
5) Mencionar WhatsApp al menos una vez.
6) Estilo de anuncio de redes: dinamico, optimista y llamativo.
""".strip()

    @staticmethod
    def revise_video_script_prompt(previous_payload: dict, issues: list[str], style: str) -> str:
        return (
            "Corrige el siguiente JSON de guion para resolver TODOS los problemas. "
            "Responde SOLO con JSON valido, misma estructura, mismo style y sin markdown.\n\n"
            f"Style requerido: {style}\n"
            f"Problemas detectados:\n- " + "\n- ".join(issues) + "\n\n"
            f"JSON actual:\n{json.dumps(previous_payload, ensure_ascii=False, indent=2)}"
        )

    @staticmethod
    def image_copy_prompt(context: BrandContext, brief: str, service: str) -> str:
        audience = ", ".join(context.audience)
        return f"""
Genera SOLO JSON valido, sin markdown.

Marca: {context.company_name}
Tagline: {context.tagline}
Audiencia: {audience}
CTA: {context.call_to_action}
Servicio foco: {service}
Brief creativo: {brief}

JSON esperado:
{{
  "headline": "max 10 palabras",
  "subheadline": "max 18 palabras",
  "call_to_action": "max 6 palabras",
  "service_focus": "string"
}}
""".strip()

    @staticmethod
    def revise_image_copy_prompt(previous_payload: dict, issues: list[str]) -> str:
        return (
            "Corrige el siguiente JSON creativo para resolver TODOS los problemas. "
            "Responde SOLO con JSON valido y sin markdown.\n\n"
            f"Problemas detectados:\n- " + "\n- ".join(issues) + "\n\n"
            f"JSON actual:\n{json.dumps(previous_payload, ensure_ascii=False, indent=2)}"
        )


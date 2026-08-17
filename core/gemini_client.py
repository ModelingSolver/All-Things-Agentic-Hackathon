"""
Hydra Cloud Shield — core/gemini_client.py
Wrapper autour de Gemini (via Vertex AI ou google-genai SDK) utilisé
UNIQUEMENT par l'Oracle (boxes/oracle.py) pour trancher le consensus.

Le prompt reçoit :
  - l'événement brut (Cloud Audit Log)
  - les scores/raisons de Scout, Tank, Ghost (via le ring)
  - l'historique Firestore de l'identité concernée

Il doit retourner un JSON structuré (pas du texte libre à parser à la
main) : { "verdict": "safe" | "suspect" | "critical", "score": 0-100,
"explanation": "...", "recommended_action": "..." }
"""
"""
Hydra Cloud Shield — core/gemini_client.py
Wrapper autour de Gemini (google-genai SDK) utilisé UNIQUEMENT par
l'Oracle (boxes/oracle.py) pour trancher le consensus.

Le prompt reçoit :
  - l'événement/identité concernée
  - les scores/raisons de Scout, Tank, Ghost (via le ring)
  - l'historique Firestore de l'identité concernée

Il doit retourner un JSON structuré (pas du texte libre à parser à la
main) : { "verdict": "safe" | "suspect" | "critical", "score": 0-100,
"explanation": "...", "recommended_action": "..." }
"""
import json

from google import genai
from google.genai import types

from config.settings import GEMINI_MODEL

ORACLE_SYSTEM_PROMPT = """\
Tu es l'Oracle d'un système de détection de menaces cloud distribué (Hydra Cloud Shield).
Tu reçois les signaux de plusieurs agents spécialisés :
- Scout : détection rapide, seuils bas, priorité au rappel
- Tank : analyse approfondie, croise l'historique de l'identité
- Ghost : surveillance passive, patterns temporels (horaires, rafales, nouveauté)

Ainsi que l'historique connu de l'identité concernée (verdicts précédents, score moyen).

Ton rôle : synthétiser tous ces signaux en UN verdict final, cohérent, expliqué.
Ne te contente pas de faire la moyenne des scores — pondère selon la fiabilité
de chaque source (Tank a plus de contexte que Ghost, par exemple) et signale
explicitement si les agents sont en désaccord.

Réponds STRICTEMENT en JSON valide, sans texte avant ni après, avec ce schéma exact :
{
  "verdict": "safe" | "suspect" | "critical",
  "score": <entier 0-100>,
  "explanation": "<2-3 phrases claires, en français, expliquant le raisonnement>",
  "recommended_action": "<none | monitor | revoke_iam_role | disable_service_account_key>",
  "agents_agreement": "<consensus | partial_disagreement | strong_disagreement>"
}
"""

_client = None


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client()
    return _client


def _build_user_prompt(event: dict, ring_signals: list[dict], history: dict | None) -> str:
    context = {
        "identity": event.get("identity", "unknown"),
        "signals_received": [
            {
                "source": s.get("source_role", "unknown"),
                "score": s.get("score"),
                "confidence": s.get("confidence"),
                "raisons": s.get("raisons", []),
            }
            for s in ring_signals
        ],
        "history": history or {"note": "aucune rencontre précédente enregistrée"},
    }
    return json.dumps(context, indent=2, ensure_ascii=False, default=str)


def _parse_verdict(raw_text: str) -> dict:
    """Parse la réponse Gemini en JSON, avec un fallback safe si le
    modèle dévie du format attendu (ne doit jamais planter l'Oracle)."""
    cleaned = raw_text.strip()
    # Au cas où le modèle encapsule quand même dans des ```json ... ```
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
        cleaned = cleaned.strip()

    try:
        parsed = json.loads(cleaned)
        # Validation minimale du schéma attendu
        required_keys = {"verdict", "score", "explanation", "recommended_action"}
        if not required_keys.issubset(parsed.keys()):
            raise ValueError("Champs manquants dans la réponse Gemini")
        return parsed
    except (json.JSONDecodeError, ValueError) as e:
        print(f"[GEMINI_CLIENT] ⚠️ Réponse Gemini non conforme, fallback appliqué : {e}")
        return {
            "verdict": "suspect",
            "score": 50,
            "explanation": "Le verdict n'a pas pu être déterminé automatiquement "
                            "(réponse du modèle non conforme) — vérification manuelle recommandée.",
            "recommended_action": "monitor",
            "agents_agreement": "unknown",
        }


def get_consensus_verdict(event: dict, ring_signals: list[dict], history: dict | None) -> dict:
    """
    Construit le prompt, appelle Gemini, retourne le verdict structuré.
    Ne lève pas d'exception sur un souci d'appel API — retourne un
    verdict de repli "suspect/monitor" pour ne jamais bloquer la ruche
    silencieusement sur un événement potentiellement important.
    """
    client = _get_client()
    user_prompt = _build_user_prompt(event, ring_signals, history)

    try:
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=ORACLE_SYSTEM_PROMPT,
                temperature=0.2,  # peu de créativité voulue, on veut de la cohérence
                response_mime_type="application/json",
            ),
        )
        return _parse_verdict(response.text)
    except Exception as e:
        print(f"[GEMINI_CLIENT] ⚠️ Appel Gemini échoué : {e}")
        return {
            "verdict": "suspect",
            "score": 50,
            "explanation": f"Appel Gemini indisponible ({e}) — vérification manuelle recommandée.",
            "recommended_action": "monitor",
            "agents_agreement": "unknown",
        }
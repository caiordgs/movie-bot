# tmdb_client.py
import os
import requests
import unicodedata
from dotenv import load_dotenv
from typing import Dict, List

# Carrega .env
load_dotenv()

# Leitura das chaves do ambiente
API_KEY_V4 = os.getenv("TMDB_API_KEY")       # Bearer token (v4), opcional
API_KEY_V3 = os.getenv("TMDB_API_KEY_V3")    # API Key v3 (curta), preferível para query params

HEADERS = {
    "Authorization": f"Bearer {API_KEY_V4}" if API_KEY_V4 else "",
    "accept": "application/json"
} if API_KEY_V4 else {}

BASE_URL = "https://api.themoviedb.org/3"

# cache simples em memória (opcional): maps (endpoint, frozenset(params.items())) -> response_json
_SIMPLE_CACHE: Dict[str, dict] = {}

# ---------- utilitários ----------
def normalize_text(text: str) -> str:
    """Remove acentos e coloca em minúsculas."""
    if not text:
        return ""
    text = text.lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", text)
        if unicodedata.category(c) != "Mn"
    )

def _cache_get(key: str):
    return _SIMPLE_CACHE.get(key)

def _cache_set(key: str, value: dict, ttl_seconds: int = 300):
    # TTL não implementado aqui; é apenas cache simples sem expiração para este projeto
    _SIMPLE_CACHE[key] = value

def _make_cache_key(url: str, params: dict) -> str:
    # transforma params em tupla ordenada para chave estável
    items = tuple(sorted((k, str(v)) for k, v in (params or {}).items()))
    return f"{url}|{items}"

# ---------- funções principais ----------
def search_movie(query: str, page: int = 1) -> dict:
    """
    Busca filmes por texto (/search/movie).
    Usa TMDB_API_KEY_V3 se existir (via param api_key). Caso contrário tenta Bearer v4.
    Retorna JSON dict ou {} em caso de erro.
    """
    if not query or not str(query).strip():
        return {}

    url = f"{BASE_URL}/search/movie"
    params = {
        "query": query,
        "page": page,
        "language": "pt-BR",
        "include_adult": False
    }

    # cache
    cache_key = _make_cache_key(url, params)
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        if API_KEY_V3:
            params["api_key"] = API_KEY_V3
            resp = requests.get(url, params=params, timeout=10)
        else:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=10)

        if resp.status_code != 200:
            print(f"Erro na API (search): status {resp.status_code} — {resp.text[:200]}")
            return {}

        data = resp.json()
        _cache_set(cache_key, data)
        return data

    except requests.exceptions.Timeout:
        print("Erro: requisição expirou (timeout). Tente novamente.")
        return {}
    except requests.exceptions.RequestException as e:
        print(f"Erro de rede/requests (search): {e}")
        return {}

def discover_movies(params: dict = None, page: int = 1) -> dict:
    """
    Usa /discover/movie. params aceita:
      - genre_id (int)
      - year (int)
      - min_vote (float) -> vote_average.gte
      - sort_by (str)
      - include_adult (bool)
      - min_vote_count (int) -> vote_count.gte (por padrão 30 se não informado)
    """
    if params is None:
        params = {}

    url = f"{BASE_URL}/discover/movie"
    api_params = {
        "page": page,
        "language": params.get("language", "pt-BR"),
    }

    if params.get("genre_id"):
        api_params["with_genres"] = str(params["genre_id"])
    if params.get("year"):
        try:
            api_params["primary_release_year"] = int(params["year"])
        except (ValueError, TypeError):
            pass
    if params.get("min_vote") is not None:
        try:
            api_params["vote_average.gte"] = float(params["min_vote"])
        except (ValueError, TypeError):
            pass
    if params.get("sort_by"):
        api_params["sort_by"] = params["sort_by"]
    if isinstance(params.get("include_adult"), bool):
        api_params["include_adult"] = str(params["include_adult"]).lower()

    # min_vote_count: usa passado ou padrão 30
    if params.get("min_vote_count") is not None:
        try:
            api_params["vote_count.gte"] = int(params["min_vote_count"])
        except (ValueError, TypeError):
            api_params["vote_count.gte"] = 30
    else:
        api_params["vote_count.gte"] = 30

    cache_key = _make_cache_key(url, api_params)
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        if API_KEY_V3:
            api_params["api_key"] = API_KEY_V3
            resp = requests.get(url, params=api_params, timeout=10)
        else:
            resp = requests.get(url, headers=HEADERS, params=api_params, timeout=10)

        if resp.status_code != 200:
            print(f"Erro na API (discover): status {resp.status_code} — {resp.text[:200]}")
            return {}

        data = resp.json()
        _cache_set(cache_key, data)
        return data

    except requests.exceptions.Timeout:
        print("Erro: requisição discover expirou (timeout).")
        return {}
    except requests.exceptions.RequestException as e:
        print(f"Erro de rede ao usar discover: {e}")
        return {}

def get_recommendations(movie_id: int, page: int = 1) -> dict:
    """
    /movie/{movie_id}/recommendations
    """
    if not movie_id:
        print("ID de filme inválido para recomendações.")
        return {}

    url = f"{BASE_URL}/movie/{movie_id}/recommendations"
    params = {"page": page, "language": "pt-BR"}

    cache_key = _make_cache_key(url, params)
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        if API_KEY_V3:
            params["api_key"] = API_KEY_V3
            resp = requests.get(url, params=params, timeout=10)
        else:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=10)

        if resp.status_code != 200:
            print(f"Erro na API (recommendations): status {resp.status_code} — {resp.text[:200]}")
            return {}

        data = resp.json()
        _cache_set(cache_key, data)
        return data

    except requests.exceptions.Timeout:
        print("Erro: requisição de recomendações expirou (timeout).")
        return {}
    except requests.exceptions.RequestException as e:
        print(f"Erro de rede ao buscar recomendações: {e}")
        return {}

def get_genres() -> dict:
    """
    Retorna dicionário normalizado {nome_normalizado: id_genero}
    """
    url = f"{BASE_URL}/genre/movie/list"
    params = {"language": "pt-BR"}

    cache_key = _make_cache_key(url, params)
    cached = _cache_get(cache_key)
    if cached:
        return cached

    try:
        if API_KEY_V3:
            params["api_key"] = API_KEY_V3
            resp = requests.get(url, params=params, timeout=10)
        else:
            resp = requests.get(url, headers=HEADERS, params=params, timeout=10)

        if resp.status_code != 200:
            print(f"Erro na API (genres): status {resp.status_code} — {resp.text[:200]}")
            return {}

        data = resp.json()
        genres = data.get("genres", [])
        genre_map = {}
        for g in genres:
            raw_name = g.get("name", "")
            genre_id = g.get("id")
            normalized = normalize_text(raw_name)
            genre_map[normalized] = genre_id

        _cache_set(cache_key, genre_map)
        return genre_map

    except requests.exceptions.RequestException as e:
        print(f"Erro ao buscar gêneros: {e}")
        return {}

# ---------- utilidades de apresentação e filtro ----------
def pretty_print_results(results: List[dict], limit: int = 5) -> None:
    """
    Imprime os filmes da lista `results` no terminal de forma legível.
    Mostra também vote_count.
    """
    if not results:
        print("Nenhum resultado para mostrar.")
        return

    limit = min(limit, len(results))
    for i in range(limit):
        item = results[i]
        title = item.get("title") or item.get("name") or "Título não disponível"
        release_date = item.get("release_date") or item.get("first_air_date") or ""
        year = release_date[:4] if release_date else "----"
        vote = item.get("vote_average")
        vote_str = f"{vote:.1f}" if isinstance(vote, (int, float)) else "-"
        movie_id = item.get("id", "N/A")
        vote_count = item.get("vote_count", 0)
        print(f"{i+1}) {title} ({year}) — Nota: {vote_str} — Avaliações: {vote_count} — ID: {movie_id}")

def filter_results_by_min_votes(results: List[dict], min_votes: int = 30) -> List[dict]:
    """
    Retorna apenas os itens cuja chave 'vote_count' >= min_votes.
    """
    if not results:
        return []
    filtered = []
    for item in results:
        try:
            vc = int(item.get("vote_count", 0) or 0)
        except (ValueError, TypeError):
            vc = 0
        if vc >= int(min_votes):
            filtered.append(item)
    return filtered

# ---------- quick smoke test quando executado diretamente ----------
if __name__ == "__main__":
    # teste rápido (não exibe chaves)
    print("tmdb_client quick test (não faz chamadas se chaves não estiverem configuradas).")
    if not (API_KEY_V3 or API_KEY_V4):
        print("Nenhuma credencial TMDB encontrada em ambiente (.env). Configure TMDB_API_KEY_V3 or TMDB_API_KEY.")
    else:
        print("Credenciais detectadas, você pode usar search_movie/get_genres/etc.")

# favorites.py (versão robusta / debug)
import json
import os
from collections import Counter
from typing import List, Dict

FAV_FILE = os.path.join(os.path.dirname(__file__), "favorites.json")

def _ensure_file():
    """Garante que o arquivo exista e seja um JSON array."""
    if not os.path.exists(FAV_FILE):
        try:
            with open(FAV_FILE, "w", encoding="utf-8") as f:
                json.dump([], f, ensure_ascii=False, indent=2)
        except Exception as e:
            raise RuntimeError(f"Não foi possível criar {FAV_FILE}: {e}")

def _read_file() -> List[Dict]:
    _ensure_file()
    try:
        with open(FAV_FILE, "r", encoding="utf-8") as f:
            return json.load(f) or []
    except Exception as e:
        # se o arquivo estiver corrompido, tenta recuperar renomeando e criando novo
        backup = FAV_FILE + ".corrupt"
        try:
            os.replace(FAV_FILE, backup)
        except Exception:
            pass
        with open(FAV_FILE, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)
        raise RuntimeError(f"Erro lendo {FAV_FILE}. Arquivo renomeado para {backup}. Detalhe: {e}")

def _write_file(data: List[Dict]):
    try:
        with open(FAV_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        raise RuntimeError(f"Erro ao gravar {FAV_FILE}: {e}")

def list_favorites() -> List[Dict]:
    try:
        return _read_file()
    except Exception as e:
        print("favorites.list_favorites error:", e)
        return []

def add_favorite(movie: Dict) -> bool:
    """
    Adiciona um filme à lista de favoritos.
    Salva apenas campos seguros para evitar problemas de serialização.
    """
    if not movie or "id" not in movie:
        return False
    try:
        favs = _read_file()
    except Exception as e:
        print("Erro ao ler favoritos:", e)
        return False

    if any(f.get("id") == movie["id"] for f in favs):
        return False

    safe = {
        "id":            movie.get("id"),
        "title":         movie.get("title") or movie.get("name"),
        "release_date":  movie.get("release_date"),
        "vote_average":  movie.get("vote_average"),
        "vote_count":    movie.get("vote_count"),
        "genre_ids":     movie.get("genre_ids", []),
        "poster_path":   movie.get("poster_path"),  # 👈 ADICIONADO
        "backdrop_path": movie.get("backdrop_path"),  # opcional, pode ser útil depois
    }

    favs.append(safe)
    try:
        _write_file(favs)
        return True
    except Exception as e:
        print("Erro ao salvar favorito:", e)
        return False

def remove_favorite(movie_id: int) -> bool:
    try:
        favs = _read_file()
    except Exception as e:
        print("Erro ao ler favoritos:", e)
        return False
    new = [f for f in favs if f.get("id") != movie_id]
    if len(new) == len(favs):
        return False
    try:
        _write_file(new)
        return True
    except Exception as e:
        print("Erro ao gravar ao remover favorito:", e)
        return False

def top_genres_from_favorites(top_n: int = 3) -> List[int]:
    favs = list_favorites()
    counter = Counter()
    for f in favs:
        for gid in f.get("genre_ids", []) or []:
            try:
                counter[int(gid)] += 1
            except Exception:
                pass
    return [gid for gid, _ in counter.most_common(top_n)]

def is_favorite(movie_id: int) -> bool:
    favs = list_favorites()
    return any(f.get("id") == movie_id for f in favs)

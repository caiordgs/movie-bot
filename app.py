import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

import os
import streamlit as st
import json
from favorites import list_favorites, add_favorite, remove_favorite

from collections import Counter
import math

from tmdb_client import (
    search_movie,
    discover_movies,
    get_genres,
    get_recommendations,
)
from favorites import (
    add_favorite,
    list_favorites,
    remove_favorite,
    top_genres_from_favorites,
)

# ---------------------- CONFIG BÁSICA ---------------------- #

st.set_page_config(
    page_title="MovieBot",
    page_icon="🎬",
    layout="wide",
)

@st.cache_data(ttl=300)  # guarda 5 minutos
def cached_search_movie(query: str, page: int = 1):
    return search_movie(query, page=page)

@st.cache_data(ttl=600)
def cached_discover_movies(params: dict, page: int = 1):
    return discover_movies(params, page=page)

# cache para vídeos (5 minutos)
@st.cache_data(ttl=300)
def cached_get_movie_videos(movie_id: int):
    # import local para evitar problemas de import circular (seguro aqui)
    from tmdb_client import get_movie_videos
    return get_movie_videos(movie_id) or {}

# CSS simples para dar uma cara de app
st.markdown(
    """
    <style>
    .main-title {
        font-size: 2.3rem;
        font-weight: 700;
        margin-bottom: 0.2rem;
    }
    .main-subtitle {
        font-size: 0.95rem;
        color: #bbbbbb;
        margin-bottom: 1.5rem;
    }
    .section-header {
        font-size: 1.3rem;
        font-weight: 600;
        margin-top: 0.5rem;
        margin-bottom: 0.3rem;
    }
    .movie-meta {
        font-size: 0.9rem;
        color: #cccccc;
    }
    .small-label {
        font-size: 0.8rem;
        color: #aaaaaa;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------- HELPERS ---------------------- #

def precision_at_k(recommended, relevant_set, k):
    return len(set(recommended[:k]) & set(relevant_set)) / k


def build_genre_id_to_name_map():
    # st.session_state["genres_map"] tem nome_normalizado -> id
    gm = st.session_state.get("genres_map", {}) or {}
    id_to_name = {}
    for name_norm, gid in gm.items():
        # recuperar nome original (improvável recuperar original capitalization)
        id_to_name[int(gid)] = name_norm.replace("-", " ").title()
    return id_to_name

# cache invert map
if "genre_id_to_name" not in st.session_state:
    st.session_state["genre_id_to_name"] = build_genre_id_to_name_map()

def genres_names_from_ids(ids_list):
    id_map = st.session_state.get("genre_id_to_name", {})
    return [id_map.get(int(g), str(g)) for g in (ids_list or [])]


def recommend_from_favorites(favs, top_n_genres=3, candidates_per_genre=40):
    if not favs:
        return []

    # 1) gênero pesos
    counter = Counter()
    for f in favs:
        for gid in f.get("genre_ids", []):
            counter[int(gid)] += 1
    if not counter:
        return []

    total = sum(counter.values())
    genre_weights = {gid: count / total for gid, count in counter.items()}
    # top genres
    top_genres = [gid for gid, _ in counter.most_common(top_n_genres)]

    # 2) coletar candidatos via discover (cachear)
    candidates = {}
    for gid in top_genres:
        params = {"genre_id": gid, "min_vote_count": 30, "sort_by": "popularity.desc"}
        resp = cached_discover_movies(params, page=1)  # usa cache
        results = resp.get("results", []) if resp else []
        # pega N por gênero
        for m in results[:candidates_per_genre]:
            mid = m.get("id")
            if not mid:
                continue
            candidates[mid] = m  # dedupe simples; manter último (popularity.desc)

    # 3) normalizações para scoring
    # calculamos max/min para vote_average e popularity para normalizar
    votes = [m.get("vote_average", 0) for m in candidates.values()]
    pops = [m.get("popularity", 0) for m in candidates.values()]
    max_vote = max(votes) if votes else 1
    min_vote = min(votes) if votes else 0
    max_pop = max(pops) if pops else 1
    min_pop = min(pops) if pops else 0

    def norm(x, mn, mx):
        if mx == mn:
            return 0.0
        return (x - mn) / (mx - mn)

    scored = []
    for m in candidates.values():
        ga_score = 0.0
        for gid in m.get("genre_ids", []):
            if gid in genre_weights:
                ga_score += genre_weights[gid]
        vote_norm = norm(m.get("vote_average", 0), min_vote, max_vote)
        pop_norm = norm(m.get("popularity", 0), min_pop, max_pop)
        # peso: 0.55 vote_norm, 0.35 pop_norm, 0.10 genre affinity
        score = 0.55 * vote_norm + 0.35 * pop_norm + 0.10 * ga_score
        scored.append((score, m))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for s, m in scored]

def recommend_with_tfidf(favs, top_n_genres=3, candidates_per_genre=50, max_candidates=500,
                         weight_tfidf=0.6, weight_genre=0.2, weight_score=0.2):
    """
    Retorna lista de filmes recomendados ordenados.
    Parâmetros:
      - favs: lista de filmes (favoritos) - cada item tem 'overview', 'genre_ids', 'vote_average', 'popularity'
      - top_n_genres: quantos gêneros considerar (por frequência)
      - candidates_per_genre: quantos candidatos coletar por gênero via discover
      - max_candidates: limite global (deduplicado)
      - weight_tfidf / weight_genre / weight_score: pesos combinados que somam 1.0
    """
    if not favs:
        return []

    # 1) calcular os gêneros preferidos (pesos)
    from collections import Counter
    counter = Counter()
    for f in favs:
        for gid in f.get("genre_ids", []) or []:
            counter[int(gid)] += 1
    if not counter:
        return []

    total = sum(counter.values())
    genre_weights = {gid: count / total for gid, count in counter.items()}
    top_genres = [gid for gid, _ in counter.most_common(top_n_genres)]

    # 2) coletar candidatos (usando cached_discover_movies se disponível)
    candidates = {}
    for gid in top_genres:
        params = {"genre_id": gid, "min_vote_count": 10, "sort_by": "popularity.desc"}
        try:
            # use cached wrapper if você já tiver: cached_discover_movies
            resp = cached_discover_movies(params, page=1)
        except Exception:
            # fallback para discover_movies direto
            resp = discover_movies(params)
        results = resp.get("results", []) if resp else []
        for m in results[:candidates_per_genre]:
            mid = m.get("id")
            if not mid:
                continue
            # evita favoritar/recomendar o mesmo da lista de favoritos
            if any(f.get("id") == mid for f in favs):
                continue
            candidates[mid] = m
            if len(candidates) >= max_candidates:
                break
        if len(candidates) >= max_candidates:
            break

    if not candidates:
        return []

    candidates_list = list(candidates.values())

    # 3) construir corpora para TF-IDF: sobreviews de favorites (concat) vs candidates
    # Criamos um "perfil textual" do usuário concatenando overviews dos favoritos
    fav_texts = [ (f.get("overview") or "") for f in favs ]
    user_profile_text = " ".join(fav_texts) if fav_texts else ""

    candidate_texts = [ (c.get("overview") or "") for c in candidates_list ]

    # Se todos os overviews estiverem vazios, desiste do TF-IDF (apenas usa outros sinais)
    use_tfidf = any(len(t.strip()) > 0 for t in candidate_texts + [user_profile_text])

    tfidf_scores = np.zeros(len(candidates_list))
    if use_tfidf:
        corpus = [user_profile_text] + candidate_texts
        vect = TfidfVectorizer(stop_words="english", max_features=5000)
        X = vect.fit_transform(corpus)  # shape (1 + N, F)
        user_vec = X[0]
        cand_vecs = X[1:]
        # similaridade cosseno entre user e cada candidato
        sims = cosine_similarity(user_vec, cand_vecs).flatten()  # shape (N,)
        # normalizar entre 0 e 1
        if sims.max() - sims.min() > 0:
            tfidf_scores = (sims - sims.min()) / (sims.max() - sims.min())
        else:
            tfidf_scores = sims

    # 4) calcular score de gênero para cada candidato (soma dos pesos dos gêneros que se cruzam)
    genre_scores = np.zeros(len(candidates_list))
    for i, c in enumerate(candidates_list):
        ga = 0.0
        for gid in (c.get("genre_ids") or []):
            ga += genre_weights.get(int(gid), 0.0)
        genre_scores[i] = ga
    # normalizar
    if genre_scores.max() - genre_scores.min() > 0:
        genre_scores = (genre_scores - genre_scores.min()) / (genre_scores.max() - genre_scores.min())

    # 5) score por nota/popularidade
    vote_arr = np.array([float(c.get("vote_average") or 0.0) for c in candidates_list])
    pop_arr = np.array([float(c.get("popularity") or 0.0) for c in candidates_list])
    # normaliza cada um
    def norm(a):
        if a.max() - a.min() > 0:
            return (a - a.min()) / (a.max() - a.min())
        return np.zeros_like(a)
    vote_n = norm(vote_arr)
    pop_n = norm(pop_arr)
    score_num = 0.6 * vote_n + 0.4 * pop_n
    if score_num.max() - score_num.min() > 0:
        score_num = (score_num - score_num.min()) / (score_num.max() - score_num.min())
    else:
        score_num = score_num

    # 6) combinar tudo com pesos configuráveis
    final_scores = (weight_tfidf * tfidf_scores) + (weight_genre * genre_scores) + (weight_score * score_num)

    # 7) anexar score e ordenar
    scored = []
    for i, m in enumerate(candidates_list):
        scored.append((final_scores[i], m))
    scored.sort(key=lambda x: x[0], reverse=True)

    # retorna só os filmes (ordem)
    return [m for s, m in scored]

def get_poster_url(movie: dict, size: str = "w200") -> str | None:
    poster_path = movie.get("poster_path")
    if not poster_path:
        return None
    return f"https://image.tmdb.org/t/p/{size}{poster_path}"


def render_movie_card(
    movie: dict,
    key_prefix: str,
    show_favorite: bool = True,
    show_remove: bool = False,
) -> None:
    """
    Renderiza um "card" de filme com poster, infos, botões e modal de detalhes com trailer.
    """
    from favorites import is_favorite  # import local para evitar confusão

    title = movie.get("title") or movie.get("name") or "Título não disponível"
    year = (movie.get("release_date") or movie.get("first_air_date") or "")[:4] or "----"
    vote = movie.get("vote_average", "-")
    vote_count = movie.get("vote_count", 0)
    movie_id = movie.get("id")

    cols = st.columns([1, 4, 1])

    # Poster
    poster_path = movie.get("poster_path")
    if poster_path:
        poster_url = f"https://image.tmdb.org/t/p/w200{poster_path}"
        cols[0].image(poster_url, width=120)
    else:
        cols[0].write("🎞️\n(sem poster)")

    # Infos
    cols[1].markdown(f"**{title}** ({year})")
    cols[1].markdown(f"⭐ {vote}  |  👥 {vote_count} avaliações")
    overview = movie.get("overview") or ""
    if overview:
        cols[1].write(overview[:260] + ("..." if len(overview) > 260 else ""))

    # badges de genero (se você implementou genres id->name)
    if st.session_state.get("genre_id_to_name"):
        gids = movie.get("genre_ids", []) or []
        if gids:
            names = [st.session_state["genre_id_to_name"].get(int(g), str(g)) for g in gids]
            badges_html = " ".join(
                [f"<span style='display:inline-block;padding:3px 8px;border-radius:12px;background:#efefef;margin-right:6px;font-size:0.8rem'>{n}</span>" for n in names]
            )
            cols[1].markdown(badges_html, unsafe_allow_html=True)

    # Ações (favoritar / remover / detalhes)
    action_area = cols[2]

    # mostrar se já é favorito
    if show_favorite:
        if is_favorite(movie_id):
            action_area.write("✅ Já favorito")
        else:
            fav_key = f"{key_prefix}-fav-{movie_id}"
            if action_area.button("❤️ Favoritar", key=fav_key):
                try:
                    ok = add_favorite(movie)
                    if ok:
                        st.success("Filme adicionado aos favoritos.")
                    else:
                        st.info("Esse filme já está nos favoritos.")
                except Exception as exc:
                    st.error(f"Erro ao favoritar: {exc}")

    if show_remove:
        rem_key = f"{key_prefix}-rem-{movie_id}"
        if action_area.button("🗑️ Remover", key=rem_key):
            try:
                ok = remove_favorite(movie_id)
                if ok:
                    st.success("Filme removido dos favoritos.")
                else:
                    st.error("Não foi possível remover.")
            except Exception as exc:
                st.error(f"Erro ao remover: {exc}")

    # Detalhes -> modal (ou expander fallback)
    det_key = f"{key_prefix}-det-{movie_id}"
    if action_area.button("ℹ️ Detalhes", key=det_key):
        # pega vídeos em cache (pode demorar na 1a vez)
        vids_json = cached_get_movie_videos(movie_id)
        vids = vids_json.get("results", []) if isinstance(vids_json, dict) else []

        # prioriza YouTube trailers
        yt = None
        for v in vids:
            if v.get("site", "").lower() == "youtube" and v.get("type", "").lower() == "trailer":
                yt = v
                break
        if not yt:
            # fallback: qualquer YouTube
            for v in vids:
                if v.get("site", "").lower() == "youtube":
                    yt = v
                    break

        # try modal if available
        try:
            with st.modal(f"Detalhes — {title}", key=f"modal-{movie_id}"):
                # poster maior
                poster_big = None
                if poster_path:
                    poster_big = f"https://image.tmdb.org/t/p/w342{poster_path}"
                    st.image(poster_big, width=300)
                st.header(title)
                st.markdown(f"**Lançamento:** {movie.get('release_date','-')}")
                st.markdown(f"**Nota:** {movie.get('vote_average','-')} — {movie.get('vote_count',0)} avaliações")
                st.write(movie.get("overview", "Sem descrição."))

                if yt:
                    # vídeo do YouTube
                    youtube_key = yt.get("key")
                    st.video(f"https://www.youtube.com/watch?v={youtube_key}")
                else:
                    st.info("Trailer não disponível.")
        except AttributeError:
            # fallback se modal não existir
            with st.expander(f"Detalhes — {title}", expanded=True):
                poster_big = None
                if poster_path:
                    poster_big = f"https://image.tmdb.org/t/p/w342{poster_path}"
                    st.image(poster_big, width=300)
                st.header(title)
                st.markdown(f"**Lançamento:** {movie.get('release_date','-')}")
                st.markdown(f"**Nota:** {movie.get('vote_average','-')} — {movie.get('vote_count',0)} avaliações")
                st.write(movie.get("overview", "Sem descrição."))
                if yt:
                    st.video(f"https://www.youtube.com/watch?v={yt.get('key')}")
                else:
                    st.info("Trailer não disponível.")

# ---------------------- ESTADO INICIAL ---------------------- #

if "search" not in st.session_state:
    st.session_state["search"] = {
        "term": "",
        "min_votes": 30,
        "page": 1,
        "results": [],
    }

if "genres_map" not in st.session_state:
    st.session_state["genres_map"] = get_genres() or {}


# ---------------------- TÍTULO GERAL ---------------------- #

st.markdown('<div class="main-title">🎬 MovieBot</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="main-subtitle">Descubra filmes, salve favoritos e receba recomendações inteligentes usando a API do TMDB.</div>',
    unsafe_allow_html=True,
)

tabs = st.tabs(
    [
        "🔍 Buscar por termo",
        "🎭 Buscar por gênero",
        "⭐ Favoritos",
        "🎯 Recomendações (Favoritos)",
    ]
)

# ============================================================
#  ABA 1 - BUSCAR POR TERMO
# ============================================================ #

with tabs[0]:
    st.markdown('<div class="section-header">🔍 Buscar por termo</div>', unsafe_allow_html=True)
    col_search, col_opts = st.columns([3, 2])

    # inicializa estado se necessário
    if "search" not in st.session_state:
        st.session_state["search"] = {
            "term": "",
            "min_votes": 30,
            "page": 1,
            "results": [],
            "total_pages": 1,
            "total_results": 0,
        }

    data = st.session_state["search"]

    with col_search:
        term = st.text_input("Digite um título, parte do nome, ator etc.", value=data["term"])

    with col_opts:
        min_votes = st.slider(
            "Mínimo de avaliações",
            min_value=0,
            max_value=2000,
            value=int(data["min_votes"]),
            step=10,
        )
        # mostramos info de página, mas não input de página manual
        st.markdown(f"**Página atual:** {data.get('page',1)} / {data.get('total_pages',1)}")

    # ação de buscar: sempre reseta para página 1
    if st.button("Buscar 🔎"):
        resp = cached_search_movie(term, page=1)
        results = resp.get("results", []) if resp else []
        total_pages = resp.get("total_pages", 1) if resp else 1
        total_results = resp.get("total_results", len(results)) if resp else len(results)
        st.session_state["search"] = {
            "term": term,
            "min_votes": int(min_votes),
            "page": 1,
            "results": results,
            "total_pages": int(total_pages) if total_pages else 1,
            "total_results": int(total_results) if total_results else len(results),
        }

    # PAGINAÇÃO: botões Anterior / Próxima
    col_prev_next = st.columns([1, 1])
    prev_disabled = st.session_state["search"]["page"] <= 1
    next_disabled = st.session_state["search"]["page"] >= st.session_state["search"].get("total_pages", 1)

    if col_prev_next[0].button("⬅️ Anterior", disabled=prev_disabled):
        new_page = max(1, st.session_state["search"]["page"] - 1)
        resp = search_movie(st.session_state["search"]["term"], page=new_page)
        results = resp.get("results", []) if resp else []
        total_pages = resp.get("total_pages", 1) if resp else 1
        total_results = resp.get("total_results", len(results)) if resp else len(results)
        st.session_state["search"].update({
            "page": new_page,
            "results": results,
            "total_pages": int(total_pages) if total_pages else 1,
            "total_results": int(total_results) if total_results else len(results),
        })

    if col_prev_next[1].button("Próxima ➡️", disabled=next_disabled):
        new_page = min(st.session_state["search"].get("total_pages", 1), st.session_state["search"]["page"] + 1)
        resp = search_movie(st.session_state["search"]["term"], page=new_page)
        results = resp.get("results", []) if resp else []
        total_pages = resp.get("total_pages", 1) if resp else 1
        total_results = resp.get("total_results", len(results)) if resp else len(results)
        st.session_state["search"].update({
            "page": new_page,
            "results": results,
            "total_pages": int(total_pages) if total_pages else 1,
            "total_results": int(total_results) if total_results else len(results),
        })

    # Renderização dos resultados a partir do session_state (sempre)
    data = st.session_state["search"]
    results = data.get("results", [])

    if not results:
        st.info("Nenhuma busca feita ainda ou nenhum resultado para esse termo.")
    else:
        st.caption(
            f"Resultados para **\"{data['term']}\"** — página {data['page']} / {data.get('total_pages',1)} — mínimo de {data['min_votes']} avaliações — {data.get('total_results', len(results))} resultados"
        )

        count = 0
        for movie in results:
            if (movie.get("vote_count") or 0) < data["min_votes"]:
                continue
            render_movie_card(movie, key_prefix=f"search-p{data['page']}", show_favorite=True, show_remove=False)
            count += 1

        if count == 0:
            st.warning(
                "Nenhum resultado atingiu o mínimo de avaliações nesta página. Experimente próxima página ou diminua o filtro."
            )
# prefetch próxima página (somente se houver próxima)
current_page = st.session_state["search"]["page"]
total_pages = st.session_state["search"].get("total_pages", 1)
if current_page < total_pages:
    try:
        # dispara cache para page+1 (não bloqueante, mas cachea o resultado)
        _ = cached_search_movie(st.session_state["search"]["term"], page=current_page + 1)
    except Exception:
        pass



# ============================================================
#  ABA 2 - BUSCAR POR GÊNERO
# ============================================================ #

with tabs[1]:
    st.markdown('<div class="section-header">🎭 Buscar por gênero</div>', unsafe_allow_html=True)

    genres_map = st.session_state["genres_map"]
    if not genres_map:
        st.error("Não foi possível carregar a lista de gêneros. Verifique suas credenciais TMDB.")
    else:
        # Mostra os nomes normalizados, mas poderíamos melhorar isso pegando da própria API em PT-BR
        genre_names = sorted(genres_map.keys())

        col_left, col_right = st.columns([2, 3])
        with col_left:
            chosen_genre_key = st.selectbox("Gênero", ["(escolha)"] + genre_names)
        with col_right:
            year = st.text_input("Ano (opcional)", value="")
            min_votes_genre = st.slider(
                "Mínimo de avaliações",
                min_value=0,
                max_value=2000,
                value=50,
                step=10,
            )

        if st.button("Buscar por gênero 🎭"):
            if chosen_genre_key == "(escolha)":
                st.warning("Escolha um gênero primeiro.")
            else:
                genre_id = genres_map.get(chosen_genre_key)
                params = {
                    "genre_id": genre_id,
                    "min_vote_count": int(min_votes_genre),
                    "sort_by": "vote_average.desc",
                }
                if year.strip().isdigit():
                    params["year"] = int(year.strip())

                resp = cached_discover_movies(params)
                results = resp.get("results", []) if resp else []

                if not results:
                    st.info("Nenhum resultado encontrado para esses filtros.")
                else:
                    st.caption(
                        f"Gênero **{chosen_genre_key}** — mínimo de {min_votes_genre} avaliações."
                    )
                    for movie in results[:40]:
                        render_movie_card(
                            movie,
                            key_prefix="genre",
                            show_favorite=True,
                            show_remove=False,
                        )

# ============================================================
#  ABA 3 - FAVORITOS
# ============================================================ #

with tabs[2]:
    st.markdown('<div class="section-header">⭐ Seus favoritos</div>', unsafe_allow_html=True)

    favs = list_favorites()
    if favs:
        st.download_button(
            "⬇️ Exportar favoritos (JSON)",
            data=json.dumps(favs, ensure_ascii=False, indent=2),
            file_name="favorites_export.json",
            mime="application/json"
        )

    # importar (merge)
    uploaded = st.file_uploader("📁 Importar favoritos (JSON)", type=["json"])
    if uploaded:
        try:
            payload = json.load(uploaded)
            added = 0
            for m in payload:
                if add_favorite(m):
                    added += 1
            st.success(f"Importados / adicionados {added} novos favoritos.")
        except Exception as e:
            st.error(f"Erro ao importar: {e}")

    # limpar favoritos (perigoso) — pedir confirmação
    if st.button("🧹 Limpar todos os favoritos"):
        st.warning("Isso remove todos os favoritos DE FORMA PERMANENTE.")
        if st.button("Confirmar limpeza (Clique de novo para confirmar)"):
            # remove todos
            for f in list_favorites():
                remove_favorite(f.get("id"))
            st.success("Todos os favoritos foram removidos.")

    favs = list_favorites()
    if not favs:
        st.info("Você ainda não adicionou filmes aos favoritos.")
    else:
        st.caption(f"Total de favoritos: {len(favs)}")
        for movie in favs:
            render_movie_card(
                movie,
                key_prefix="fav",
                show_favorite=False,
                show_remove=True,
            )

# ============================================================
#  ABA 4 - RECOMENDAÇÕES BASEADAS NOS FAVORITOS
# ============================================================ #

with tabs[3]:
    st.markdown('<div class="section-header">🎯 Recomendações baseadas nos seus favoritos</div>', unsafe_allow_html=True)

    # init session_state para guardar recomendações
    if "rec_from_favs" not in st.session_state:
        st.session_state["rec_from_favs"] = []

    favs = list_favorites()
    if not favs:
        st.info("Você ainda não tem favoritos suficientes para gerar recomendações.")
    else:
        st.write("Vamos analisar seus favoritos e gerar recomendações usando IA (TF-IDF + gênero + score).")

        if st.button("Gerar recomendações 🎯"):
            with st.spinner("Calculando recomendações com IA..."):
                recs = recommend_with_tfidf(
                    favs,
                    top_n_genres=3,
                    candidates_per_genre=50,
                    max_candidates=400,
                    weight_tfidf=0.6,
                    weight_genre=0.2,
                    weight_score=0.2,
                )
                st.session_state["rec_from_favs"] = recs

        # Renderização SEMPRE usando session_state
        aggregate = st.session_state.get("rec_from_favs", [])

        if not aggregate:
            st.info("Nenhuma recomendação ainda. Clique em 'Gerar recomendações 🎯'.")
        else:
            st.caption(f"Mostrando {min(40, len(aggregate))} recomendações baseadas nos seus favoritos:")
            for movie in aggregate[:40]:
                render_movie_card(
                    movie,
                    key_prefix=f"tfdif-recfav-{movie.get('id')}",
                    show_favorite=True,
                    show_remove=False,
                )


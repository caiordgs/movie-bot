# app.py
import streamlit as st
from tmdb_client import search_movie, discover_movies, get_recommendations, get_genres, pretty_print_results
from favorites import add_favorite, list_favorites, remove_favorite, top_genres_from_favorites
from logger_conf import get_logger

logger = get_logger("streamlit-app")

st.set_page_config(page_title="MovieBot", layout="wide")
st.title("MovieBot — Recomendador de Filmes")

tabs = st.tabs(["Buscar", "Gênero", "Favoritos", "Recomendar (Favoritos)"])

with tabs[0]:
    st.header("Buscar por termo")

    # inicializa estado, se ainda não existir
    if "search_results" not in st.session_state:
        st.session_state["search_results"] = []
    if "search_meta" not in st.session_state:
        st.session_state["search_meta"] = {"page": 1, "term": "", "min_votes": 30}

    # inputs
    term = st.text_input("Termo de busca", value=st.session_state["search_meta"]["term"])
    min_votes = st.number_input(
        "Min votes", min_value=0, value=st.session_state["search_meta"]["min_votes"], step=1
    )
    page = st.number_input(
        "Página", min_value=1, value=st.session_state["search_meta"]["page"], step=1
    )

    # quando clica em Buscar, atualiza o estado
    if st.button("Buscar"):
        resp = search_movie(term, page=page)
        results = resp.get("results", []) if resp else []
        st.session_state["search_results"] = results
        st.session_state["search_meta"] = {
            "page": int(page),
            "term": term,
            "min_votes": int(min_votes),
        }

    # usa SEMPRE o que está no session_state para renderizar
    results = st.session_state["search_results"]
    meta = st.session_state["search_meta"]
    if not results:
        st.info("Nenhum resultado encontrado ou nenhuma busca feita ainda.")
    else:
        st.write(
            f'Mostrando {len(results)} resultados (página {meta["page"]}) '
            f'com mínimo de {meta["min_votes"]} avaliações.'
        )
        for r in results[:50]:
            vote_count = r.get("vote_count", 0) or 0
            if vote_count < meta["min_votes"]:
                continue  # aplica filtro aqui

            title = r.get("title") or r.get("name") or "Título não disponível"
            year = (r.get("release_date") or "")[:4] or "----"
            vote = r.get("vote_average", "-")
            movie_id = r.get("id")

            cols = st.columns([1, 4, 1])

            # col 0: poster
            poster_path = r.get("poster_path")
            if poster_path:
                poster_url = f"https://image.tmdb.org/t/p/w200{poster_path}"
                cols[0].image(poster_url, width=120)
            else:
                cols[0].write(" ")

            # col 1: info
            cols[1].markdown(
                f"**{title}** ({year})  \nNota: {vote} — Avaliações: {vote_count}"
            )
            overview = r.get("overview", "") or ""
            if overview:
                cols[1].write(
                    overview[:300] + ("..." if len(overview) > 300 else "")
                )

            # col 2: botão favoritar
            btn_label = f'❤️ Favoritar "{title}"'
            btn_key = f"fav-{movie_id}"
            if cols[2].button(btn_label, key=btn_key):
                try:
                    ok = add_favorite(r)
                    if ok:
                        st.success("Favoritado!")
                    else:
                        st.info("Já era favorito.")
                except Exception as exc:
                    st.error(f"Erro ao salvar favorito: {exc}")
                # opcional: não precisa de rerun aqui; o Streamlit já reroda

with tabs[1]:
	st.header("Buscar por gênero")
	genres_map = get_genres()
	if genres_map:
		genre_names = sorted(genres_map.keys())
		choice = st.selectbox("Escolha um gênero", [""] + genre_names)
		year = st.text_input("Ano (opcional)")
		min_votes = st.number_input("Min votes", min_value=0, value=30)
		if st.button("Buscar por gênero"):
			gid = genres_map.get(choice)
			params = {"genre_id": gid, "min_vote_count": min_votes}
			if year and year.isdigit():
				params["year"] = int(year)
			resp = discover_movies(params)
			results = resp.get("results", [])
			st.write(f"Resultados: {len(results)}")
			for r in results[:50]:
				title = r.get("title") or r.get("name")
				vote = r.get("vote_average")
				vote_count = r.get("vote_count")
				year = (r.get("release_date") or "")[:4]
				movie_id = r.get("id")

				cols = st.columns([1, 4, 1])

				# Poster
				poster_path = r.get("poster_path")
				if poster_path:
					poster_url = f"https://image.tmdb.org/t/p/w200{poster_path}"
					cols[0].image(poster_url, width=120)
				else:
					cols[0].write("(sem imagem)")

				# Infos
				cols[1].markdown(
					f"**{title}** ({year})\n"
					f"Nota: {vote} — Avaliações: {vote_count}"
				)
				overview = r.get("overview", "") or ""
				cols[1].write(overview[:300] + ("..." if len(overview) > 300 else ""))

				# Favoritar
				btn_label = f'❤️ Favoritar "{title}"'
				btn_key = f"fav-{movie_id}"

				if cols[2].button(btn_label, key=btn_key):
					ok = add_favorite(r)
					if ok:
						st.success("Favoritado!")
					else:
						st.info("Já era favorito.")

with tabs[2]:
    st.header("Seus Favoritos")

    favs = list_favorites()
    if not favs:
        st.info("Nenhum favorito salvo ainda.")
    else:
        st.write(f"Total: {len(favs)} filmes\n")

        for f in favs:
            title = f.get("title") or "Título não disponível"
            year = (f.get("release_date") or "")[:4]
            vote = f.get("vote_average", "-")
            vote_count = f.get("vote_count", 0)
            movie_id = f.get("id")

            cols = st.columns([1, 4, 1])

            # Poster do filme
            poster_path = f.get("poster_path")
            if poster_path:
                poster_url = f"https://image.tmdb.org/t/p/w200{poster_path}"
                cols[0].image(poster_url, width=120)
            else:
                cols[0].write(" ")

            # Informações
            cols[1].markdown(
                f"**{title}** ({year})  \n"
                f"Nota: {vote} — Avaliações: {vote_count}"
            )

            # Botão remover
            if cols[2].button("🗑️ Remover", key=f"rem-{movie_id}"):
                remove_favorite(movie_id)
                st.success("Removido!")



with tabs[3]:
	st.header("Recomendações baseadas nos seus favoritos")
	if st.button("Gerar recomendações"):
		top_genres = top_genres_from_favorites(3)
		st.write("Top genres IDs:", top_genres)
		aggregate = []
		seen = set()
		for g in top_genres:
			resp = discover_movies({"genre_id": g, "min_vote_count": 30, "sort_by": "vote_average.desc"})
			for r in resp.get("results", []):
				if r.get("id") in seen:
					continue
				seen.add(r.get("id"))
				aggregate.append(r)
		st.write(f"Encontradas {len(aggregate)} recomendações")
		for r in results[:50]:
			title = r.get("title") or r.get("name")
			vote = r.get("vote_average")
			vote_count = r.get("vote_count")
			year = (r.get("release_date") or "")[:4]
			movie_id = r.get("id")

			cols = st.columns([1, 4, 1])

			# Poster
			poster_path = r.get("poster_path")
			if poster_path:
				poster_url = f"https://image.tmdb.org/t/p/w200{poster_path}"
				cols[0].image(poster_url, width=120)
			else:
				cols[0].write("(sem imagem)")

			# Infos
			cols[1].markdown(
				f"**{title}** ({year})\n"
				f"Nota: {vote} — Avaliações: {vote_count}"
			)

			overview = r.get("overview", "") or ""
			cols[1].write(overview[:300] + ("..." if len(overview) > 300 else ""))

			# Favoritar
			if cols[2].button(f'❤️ Favoritar "{title}"', key=f"fav-rec-{movie_id}"):
				ok = add_favorite(r)
				if ok:
					st.success("Favoritado!")
				else:
					st.info("Já era favorito.")

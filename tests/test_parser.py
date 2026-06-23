from watcher import parse_vacancies


def test_parses_individual_room_link():
    html = """
    <section>
      <div class="room-card">
        <a href="/chintai/kanto/kanagawa/room/40_3290_2_307.html">
          サンヴァリエ日吉 2号棟 307号室 143,200円 2LDK 62㎡
        </a>
      </div>
    </section>
    """
    vacancies = parse_vacancies(html, "https://www.ur-net.go.jp/chintai/kanto/kanagawa/40_3290.html")
    assert len(vacancies) == 1
    item = next(iter(vacancies))
    assert "307号室" in item.title
    assert item.url.startswith("https://www.ur-net.go.jp/")


def test_falls_back_to_property_link():
    html = '<div><a href="/chintai/kanto/kanagawa/40_3290.html">サンヴァリエ日吉 空室状況 2</a></div>'
    vacancies = parse_vacancies(html, "https://www.ur-net.go.jp/chintai/kanto/kanagawa/result/")
    assert len(vacancies) == 1

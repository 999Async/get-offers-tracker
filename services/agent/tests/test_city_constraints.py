import pytest

from getoffers_agent.job_search.constraints import resolve_city_constraints
from getoffers_agent.job_search.contracts import HardConstraints, SearchRequest


@pytest.mark.parametrize(
    ("query", "included", "excluded"),
    [
        ("在深圳找 Python 工作", ("深圳",), ()),
        ("深圳市的算法岗位", ("深圳",), ()),
        ("深圳或北京的 Python 岗位", ("北京", "深圳"), ()),
        ("找北京或深圳岗位", ("北京", "深圳"), ()),
        ("Python 岗位，不要深圳", (), ("深圳",)),
        ("不要深圳、北京的 Python 岗位", (), ("北京", "深圳")),
        ("在北京找 Python 工作，不要深圳", ("北京",), ("深圳",)),
        ("Python 深圳优先", (), ()),
        ("优先深圳，北京也可以", (), ()),
        ("深圳或北京优先", (), ()),
        ("地点不限深圳", (), ()),
        ("深圳大学的 Python 岗位", (), ()),
        ("需要出差到深圳的 Python 岗位", (), ()),
        ("Find Python jobs in FONTANA", ("Fontana, CA",), ()),
        ("Python Engineer — Fontana, CA (Customer Site)", ("Fontana, CA",), ()),
        ("Find Python jobs in Fontana or San Jose", ("Fontana, CA", "San Jose, CA"), ()),
        ("Find Python jobs, not in Fontana", (), ("Fontana, CA",)),
        ("Find Python jobs preferably in Fontana", (), ()),
        ("Find Python jobs in Fontana preferred", (), ()),
        ("Find jobs serving customers in Fontana", (), ()),
        ("I worked in Fontana; find Python jobs", (), ()),
        ("Find jobs working with Grenoble customers", (), ()),
        ("Research Engineer, AI", (), ()),
        ("Python Engineer, CA", (), ()),
    ],
)
def test_city_intent(query, included, excluded):
    request = SearchRequest(query=query)
    constraints, _ = resolve_city_constraints(
        request, ("深圳", "北京", "Fontana, CA", "San Jose, CA", "Reno, NV")
    )
    assert constraints.cities == included
    assert constraints.excluded_cities == excluded
    assert request.hard_constraints.cities == ()


def test_city_aliases_intersect_explicit_scope_without_losing_other_constraints():
    request = SearchRequest(
        query="Find Python roles in fontana",
        hard_constraints=HardConstraints(
            cities=("Fontana", "San Jose, CA"),
            excluded_terms=("Java",),
            max_age_days=7,
        ),
    )
    constraints, _ = resolve_city_constraints(request, ("Fontana, CA", "San Jose, CA"))
    assert constraints.cities == ("Fontana, CA",)
    assert constraints.excluded_terms == ("Java",)
    assert constraints.max_age_days == 7


@pytest.mark.parametrize("query", ["在北京找工作", "不要深圳的岗位"])
def test_contradictory_city_constraints_are_not_silently_relaxed(query):
    request = SearchRequest(query=query, hard_constraints=HardConstraints(cities=("深圳",)))
    with pytest.raises(ValueError, match="conflicting_city_constraints"):
        resolve_city_constraints(request, ("深圳", "北京"))


@pytest.mark.parametrize(
    "query,city",
    [
        ("在北京找工作", "北京"),
        ("Python Engineer — Fontana, CA (Customer Site)", "Fontana, CA"),
    ],
)
def test_absent_city_does_not_mean_unrestricted(query, city):
    constraints, _ = resolve_city_constraints(SearchRequest(query=query), ())
    assert constraints.cities == (city,)

from ncfbot.router import route


def test_explicit_identity_wins_over_competing_keywords():
    result = route("I am a professor asking about tuition and admissions for my advisee.")
    assert result.route == "faculty"
    assert result.matched_signals


def test_explicit_identity_supports_contractions():
    assert route("I'm faculty and need the public advising steps.").route == "faculty"
    assert route("I’m a prospective student looking at programs.").route == "outside"


def test_explicit_role_switch_overrides_conversation_context():
    result = route("I am a student now and need help with my course.", previous_role="outside")
    assert result.route == "students"
    assert "Explicit user identity" in result.reason


def test_inferred_audience_exposes_signals():
    result = route("Can I add a class and will it affect my thesis?")
    assert result.route == "students"
    assert "add a class" in result.matched_signals


def test_role_independent_question_does_not_force_classification():
    result = route("Where is the campus map?")
    assert result.route == "role-independent"


def test_weak_evidence_is_ambiguous():
    result = route("How does this work?")
    assert result.route == "ambiguous"
    assert result.matched_signals == ()


def test_tied_signals_are_ambiguous():
    result = route("This is about my course and admissions.")
    assert result.route == "ambiguous"
    assert any(signal.startswith("students:") for signal in result.matched_signals)
    assert any(signal.startswith("outside:") for signal in result.matched_signals)


def test_previous_role_supplies_weak_context_only():
    result = route("What should I do next?", previous_role="faculty")
    assert result.route == "faculty"
    assert result.matched_signals == ("conversation:faculty",)

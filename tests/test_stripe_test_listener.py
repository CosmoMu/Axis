from __future__ import annotations

from scripts.run_stripe_test_listener import STRIPE_TEST_EVENTS, redact_stripe_output


def test_stripe_test_listener_registers_required_events() -> None:
    assert STRIPE_TEST_EVENTS == (
        "checkout.session.completed",
        "invoice.paid",
        "invoice.payment_failed",
        "customer.subscription.updated",
        "customer.subscription.deleted",
    )


def test_stripe_test_listener_redacts_secrets() -> None:
    assert (
        redact_stripe_output("Ready! whsec_example123 using sk_test_example456")
        == "Ready! <redacted> using <redacted>"
    )

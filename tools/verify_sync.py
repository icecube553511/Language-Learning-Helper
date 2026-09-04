from __future__ import annotations

import ast
import hashlib
import json
import math
import re
import sys
import unicodedata
from pathlib import Path
from tempfile import TemporaryDirectory

import prepare_pet_appearance_assets as pet_appearance_assets
from opencc import OpenCC

from prepare_pet_asset import prepare as prepare_pet_asset


ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "shared" / "contracts"
CONTENT = ROOT / "shared" / "content"
TO_SIMPLIFIED = OpenCC("t2s")


def fail(message: str) -> None:
    raise AssertionError(message)


def verify_scheduler() -> None:
    payload = json.loads((CONTRACTS / "scheduler-golden-v1.json").read_text(encoding="utf-8"))
    if payload["algorithmVersion"] != "lexi-sm2-v1":
        fail("Unexpected scheduler version")
    initial = payload["initial"]
    for vector in payload["vectors"]:
        ease = float(initial["ease"])
        interval = float(initial["intervalDays"])
        repetitions = int(initial["repetitions"])
        lapses = int(initial["lapses"])
        rating = vector["rating"]
        if rating == "again":
            interval, ease, repetitions, lapses, state = 10 / 1440, max(1.3, ease - 0.2), 0, lapses + 1, "relearning"
        elif rating == "hard":
            interval, ease, repetitions, state = (1 if interval < 1 else max(1, interval * 1.2)), max(1.3, ease - 0.15), repetitions + 1, "learning" if repetitions == 0 else "review"
        elif rating == "good":
            interval, repetitions, state = (3 if interval < 1 else interval * ease), repetitions + 1, "review"
        elif rating == "easy":
            interval, ease, repetitions, state = (7 if interval < 1 else interval * ease * 1.3), min(3.0, ease + 0.15), repetitions + 1, "review"
        else:
            fail(f"Unknown rating: {rating}")
        actual = {
            "state": state,
            "intervalDays": interval,
            "ease": ease,
            "repetitions": repetitions,
            "lapses": lapses,
            "dueAtUtc": vector["reviewedAtUtc"] + interval * 86400,
        }
        for key, expected in vector["expected"].items():
            observed = actual[key]
            if isinstance(expected, float):
                if not math.isclose(observed, expected, rel_tol=1e-12, abs_tol=1e-9):
                    fail(f"Scheduler vector {vector['name']} differs at {key}: {observed} != {expected}")
            elif observed != expected:
                fail(f"Scheduler vector {vector['name']} differs at {key}: {observed} != {expected}")


def verify_weighted_review() -> None:
    payload = json.loads((CONTRACTS / "weighted-review-golden-v1.json").read_text(encoding="utf-8"))
    if payload.get("contractVersion") != "weighted-review-v1":
        fail("Unexpected weighted review contract version")
    expected_initial = {"again": 1.0, "hard": 0.8, "good": 0.2, "easy": 0.05}
    for vector in payload.get("ratings", []):
        rating = vector.get("rating")
        if rating not in expected_initial:
            fail(f"Unknown weighted review rating: {rating}")
        if not math.isclose(float(vector.get("initialWeight", -1)), expected_initial[rating]):
            fail(f"Initial review weight differs for {rating}")
        expected_review = (
            float(vector["previousWeight"])
            if rating in {"again", "hard"}
            else expected_initial[rating]
        )
        if not math.isclose(float(vector.get("reviewWeight", -1)), expected_review):
            fail(f"Updated review weight differs for {rating}")
    if int(payload.get("defaultBatchSize", 0)) != 20:
        fail("Unexpected default review batch size")


def verify_dictation_contract() -> None:
    contract_path = CONTRACTS / "dictation-export-v1.md"
    golden_path = CONTRACTS / "dictation-export-golden-v1.json"
    if not contract_path.is_file() or not contract_path.read_text(encoding="utf-8").strip():
        fail("Dictation export contract is missing or empty")
    if not golden_path.is_file():
        fail("Dictation export golden file is missing")
    payload = json.loads(golden_path.read_text(encoding="utf-8"))
    if payload.get("contractVersion") != "dictation-export-v1":
        fail("Unexpected dictation export contract version")
    page = payload.get("page", {})
    if page.get("size") != "A4" or page.get("orientation") != "portrait":
        fail("Dictation export must use A4 portrait")
    font_size = payload.get("fontSizePt", {})
    if (font_size.get("default"), font_size.get("minimum"), font_size.get("maximum")) != (12, 8, 24):
        fail("Unexpected dictation export font-size bounds")
    if payload.get("formats") != ["DOCX", "PDF"]:
        fail("Dictation export formats differ from the shared contract")
    if payload.get("allowedTags") != ["cet4", "cet6", "gk", "zk", "evaluated"]:
        fail("Dictation program tag allowlist differs from the shared contract")
    selection = payload.get("selectionVector", {})
    if (
        selection.get("selectedIds") != ["adapt", "re-enter"]
        or selection.get("crossGroupUnion") is not True
        or selection.get("emptySelectionFallsBackToScope") is not True
        or selection.get("sampleWithoutReplacement") is not True
    ):
        fail("Dictation random subset semantics differ from the shared contract")
    range_vector = payload.get("rangeSelectionVector", {})
    if (
        range_vector.get("inclusiveIds") != ["banana", "canada", "dear"]
        or range_vector.get("reverseInclusiveIds") != ["banana", "canada", "dear"]
        or range_vector.get("sameGroupOnly") is not True
        or range_vector.get("markerText") != "选取到这里"
        or range_vector.get("noAnchorHidesMarker") is not True
    ):
        fail("Dictation range-selection semantics differ from the shared contract")
    draft_vector = payload.get("draftVector", {})
    if draft_vector.get("version") != 1 or draft_vector.get("maxBytes") != 1048576:
        fail("Dictation draft version or size limit differs from the shared contract")
    if draft_vector.get("leaveActions") != ["save", "discard", "continue"]:
        fail("Dictation leave actions differ from the shared contract")
    draft_contract = CONTRACTS / "dictation-draft-v1.md"
    draft_contract_text = draft_contract.read_text(encoding="utf-8") if draft_contract.is_file() else ""
    if "dictation-draft-v1" not in draft_contract_text:
        fail("Dictation draft contract is missing or has the wrong version")
    for marker in ("last synced envelope", "three conflict", "encrypted local ring"):
        if marker not in draft_contract_text:
            fail(f"Dictation draft conflict-backup contract is missing {marker}")
    confirmation = payload.get("confirmation", {})
    if confirmation.get("rendered") != "当前仅选择了3/10，是否确定选择":
        fail("Dictation manual-selection confirmation text differs from the shared contract")
    evaluated = payload.get("evaluated", {})
    if evaluated.get("defaultPreference") != "ASK" or evaluated.get("preferences") != ["ASK", "ALWAYS", "NEVER"]:
        fail("Dictation evaluated preferences differ from the shared contract")
    selection_ui = payload.get("manualSelectionUi", {})
    if selection_ui.get("columns") != ["word", "meaning", "tags", "evaluationStatus", "selected"]:
        fail("Dictation manual-selection columns differ from the shared contract")
    if selection_ui.get("headings") != ["单词", "中文释义", "标签", "考察状态", "选择"]:
        fail("Dictation manual-selection headings differ from the shared contract")
    if (
        selection_ui.get("evaluatedTag") != "evaluated"
        or selection_ui.get("evaluatedText") != "已考察"
        or selection_ui.get("evaluatedColor") != "black"
        or selection_ui.get("unevaluatedText") != "未考察"
        or selection_ui.get("unevaluatedColor") != "red"
        or selection_ui.get("emptyTagsText") != "-"
        or selection_ui.get("selectionControl") != "checkbox"
        or selection_ui.get("horizontalOverflow") != "scroll"
        or selection_ui.get("rowClickSelection") is not True
        or selection_ui.get("dragMultiSelect") is not True
        or selection_ui.get("downloadAction") != "下载文档"
        or selection_ui.get("downloadPathSelection") != "user-selected"
    ):
        fail("Dictation manual-selection behavior differs from the shared contract")
    example_chinese = payload.get("exampleChineseVector", {})
    if (
        example_chinese.get("includeExample") is not True
        or example_chinese.get("includeExampleChinese") is not True
        or example_chinese.get("renderedExampleLine") != "e.g. We _________ quickly.（我们很快适应。）"
    ):
        fail("Dictation example-with-Chinese semantics differ from the shared contract")


def verify_word_bubble_contract() -> None:
    contract_path = CONTRACTS / "word-bubble-v1.md"
    golden_path = CONTRACTS / "word-bubble-golden-v1.json"
    if not contract_path.is_file() or "word-bubble-v1" not in contract_path.read_text(encoding="utf-8"):
        fail("Word bubble contract is missing or has the wrong version")
    if not golden_path.is_file():
        fail("Word bubble golden file is missing")
    payload = json.loads(golden_path.read_text(encoding="utf-8"))
    if payload.get("contractVersion") != "word-bubble-v1" or payload.get("maxDepth") != 20:
        fail("Word bubble contract version or max depth differs")
    stack_vectors = payload.get("stackVectors", {})
    if stack_vectors.get("dismissChild") != ["root"] or stack_vectors.get("dismissRoot") != []:
        fail("Word bubble dismiss semantics differ from the shared golden")
    if "bilingual example" not in contract_path.read_text(encoding="utf-8"):
        fail("Word bubble contract must require bilingual example rendering")
    parity = json.loads((CONTRACTS / "parity.json").read_text(encoding="utf-8"))
    if parity.get("wordBubbleVersion") != "word-bubble-v1":
        fail("Parity manifest does not declare word-bubble-v1")


def verify_pet_contract() -> None:
    contract_path = CONTRACTS / "pet-companion-v1.md"
    golden_path = CONTRACTS / "pet-companion-golden-v1.json"
    if not contract_path.is_file() or "pet-companion-v1" not in contract_path.read_text(encoding="utf-8"):
        fail("Pet companion contract is missing or has the wrong version")
    if not golden_path.is_file():
        fail("Pet companion golden file is missing")
    payload = json.loads(golden_path.read_text(encoding="utf-8"))
    if payload.get("contractVersion") != "pet-companion-v1" or payload.get("name") != "冰子":
        fail("Pet companion identity differs from the shared contract")
    if (
        payload.get("sourceAsset") != "shared/assets/branding/pet_image.png"
        or payload.get("runtimeAsset") != "shared/assets/pets/bingzi.png"
        or payload.get("runtimeAssetLeft") != "shared/assets/pets/bingzi-left.png"
    ):
        fail("Pet companion asset paths differ")
    if (
        payload.get("tickMs") != 16
        or payload.get("displaySize") != 112
        or payload.get("navigationTransition") != "drop-to-nearest"
    ):
        fail("Pet companion timing or navigation transition differs")
    if (
        payload.get("windowScope") != "application-owned-window"
        or payload.get("singleActivePet") is not True
        or payload.get("activeWindowBounds") != "pet-host-window"
        or payload.get("wordBubblePetScope") != "trigger-window-retained"
        or payload.get("wordBubbleExit") != "drag-and-autonomous"
        or payload.get("wordBubbleEscapeClearance") != "full-display-size"
        or payload.get("learningReminderPetCount") != 1
        or payload.get("nestedPopupOwner") != "recursive-trigger-window"
        or payload.get("activeWindowSelection") != "focus-map-host-z-order"
        or payload.get("windowDeactivationFallback") != "next-mapped-host-z-order"
        or payload.get("platformManagedUiExcluded") is not True
    ):
        fail("Pet companion window scope differs")
    if payload.get("rectangleFormat") != "x-y-width-height" or payload.get("petSizeMeaning") != "half-size":
        fail("Pet companion geometry semantics differ")
    if payload.get("targetKinds") != ["control", "surface", "chart", "edge"]:
        fail("Pet companion target kinds differ")
    if payload.get("modes") != ["idle", "slide", "roll", "fly", "fall", "bounce", "dragging", "fling"]:
        fail("Pet companion modes differ")
    if payload.get("facings") != ["left", "right"]:
        fail("Pet companion facing values differ")
    if payload.get("motion") != {
        "acceleration": 0.5,
        "cruiseSpeed": 4.0,
        "curveAcceleration": 0.25,
        "curveAccelerationPolicy": "constant-independent-of-requested-step",
        "curveLandingVelocityProjection": "world-velocity-dot-local-unit-tangent",
        "curveVelocityUnits": "logical-units-per-tick",
        "curveCoordinateScalePolicy": "logical-velocity-physical-path-budget",
        "curveLandingSpeedLimit": 8.0,
        "curveDownhillTerminalSpeed": 4.0,
        "curveDownhillResponsePerTick": 0.0625,
        "curveDirectionEpsilon": 0.000001,
        "curveLandingRestDirection": "local-positive-y-downhill",
        "curveLandingInitialUphillMotion": True,
        "curveUphillEndpointPolicy": "stop-and-reverse-downhill",
        "idleTicks": 24,
        "fallTimeStepSeconds": 0.016,
        "fallGravityLogicalUnitsPerSecondSquared": 2148.4375,
        "fallVelocityUnits": "logical-units-per-second",
        "fallIntegration": "closed-form-constant-acceleration",
        "maxFallSpeed": None,
        "hardLandingSpeed": 437.5,
        "bounceCount": 2,
        "firstBounceSpeed": 312.5,
        "bounceDecay": 0.55,
        "centerBiasWeight": 0.65,
        "edgePenaltyRatio": 0.15,
        "supportSide": "upper",
        "screenEdges": ["left", "right", "bottom"],
        "horizontalFlip": True,
        "noUpwardFall": True,
        "noBelowTargetPolicy": "fall-to-viewport-bottom-support",
        "fallAxis": "vertical-only",
        "fallTargetIntersection": "current-x-ray",
        "fallTargetRefresh": "every-tick-nearest-current-x-ray",
        "landingImpactVelocity": "continuous-contact",
        "syntheticBottomLanding": "same-impact-and-bounce-rules",
        "flingGravityLogicalUnitsPerSecondSquared": 2148.4375,
        "flingHorizontalRestitution": 0.72,
        "maxSubstepSeconds": 0.004,
        "maxSubstepsPerTick": 8,
        "highSpeedInterpolation": "linear-between-simulated-substeps",
        "flingChartContactDirection": "contact-equation-derivative-nonnegative",
    }:
        fail("Pet companion motion semantics differ")
    drag = payload.get("drag", {})
    if drag != {
        "enabled": True,
        "clampToViewport": True,
        "releaseKeepsPosition": True,
        "preserveGrabOffset": True,
        "supportedReleaseMode": "idle",
        "suspendedReleaseMode": "fall",
        "suspendedReleaseTarget": None,
        "suspendedReleaseVerticalVelocity": 0.0,
        "releaseVelocitySampleWindowMs": 120,
        "minimumFlingSpeed": 90.0,
        "maxFlingSpeed": 1800.0,
        "velocityEstimator": "weighted-terminal-linear-regression",
        "flingMode": "fling",
        "flingCollision": "continuous-contact",
    }:
        fail("Pet companion drag semantics differ")
    if payload.get("windowMigration") != {
        "enabled": True,
        "entryDirections": ["left", "right", "top"],
        "dragEntry": True,
        "boundaryPolicy": "portal-at-viewport-edge",
        "candidateSelection": "earliest-motion-intersection",
        "rayIntersection": "continuous-parametric-aabb",
        "rayMissPolicy": "reject",
        "overlapPolicy": "autonomous-reject-explicit-drag-allow",
        "positionMapping": "full-display-inner-edge",
        "stateTransfer": "preserve-velocity-and-grab-offset",
        "curveContactTransfer": "clear-source-local-target-and-velocity",
    }:
        fail("Pet companion window migration semantics differ")
    if payload.get("transientOnly") is not True:
        fail("Pet companion state must be transient")
    expected_behaviors = {
        "surface-inside-moves-to-upper-support",
        "upper-support-reverses",
        "vertical-screen-edge-remains-traversable",
        "horizontal-edge-moves-to-upper-support",
        "chart-path-reverses",
        "flight-is-vertical-first",
        "navigation-prefers-below",
        "fall-without-below-target-uses-viewport-bottom",
        "fall-accelerates",
        "hard-landing-bounces-twice",
        "fall-skips-horizontally-offset-support",
        "fall-retargets-new-nearest-support-every-tick",
        "fall-already-touching-support-lands",
        "synthetic-bottom-hard-landing-bounces-twice",
        "suspended-drag-release-enters-fall",
        "center-bias-prefers-interior",
        "center-bias-measures-nearest-support",
    }
    observed_behaviors = {item.get("name") for item in payload.get("behaviorVectors", [])}
    if observed_behaviors != expected_behaviors:
        fail("Pet companion behavior vectors differ")
    behavior_fields = {
        "surface-inside-moves-to-upper-support": {"position", "target", "step", "expectedPosition", "expectedMode"},
        "upper-support-reverses": {"position", "target", "step", "movementSpeed", "expectedPosition", "expectedMode", "expectedFacing"},
        "vertical-screen-edge-remains-traversable": {"position", "target", "step", "movementSpeed", "expectedPosition", "expectedMode"},
        "horizontal-edge-moves-to-upper-support": {"position", "target", "step", "expectedPosition", "expectedMode"},
        "chart-path-reverses": {"position", "target", "step", "ticks", "expectedMode", "mustReverse"},
        "flight-is-vertical-first": {"position", "mode", "target", "step", "movementSpeed", "expectedPosition", "expectedMode"},
        "navigation-prefers-below": {"position", "targets", "step", "expectedTarget", "expectedPosition", "expectedVerticalVelocity"},
        "fall-without-below-target-uses-viewport-bottom": {"position", "verticalVelocity", "viewport", "petHalfSize", "targets", "expectedTarget", "expectedSyntheticSupportY", "expectedPositionAfterOneTick", "expectedVerticalVelocity", "expectedMode", "expectedYDirection"},
        "fall-accelerates": {"position", "mode", "verticalVelocity", "target", "step", "expectedPosition", "expectedVerticalVelocity", "expectedMode"},
        "hard-landing-bounces-twice": {"position", "mode", "verticalVelocity", "target", "step", "expectedPosition", "expectedMode", "expectedImpactTimeSeconds", "expectedImpactVerticalVelocity", "expectedBounceVerticalVelocity", "expectedBouncesRemaining"},
        "fall-skips-horizontally-offset-support": {"position", "verticalVelocity", "viewport", "petHalfSize", "targets", "expectedTarget", "expectedPositionAfterOneTick", "expectedVerticalVelocity", "expectedMode"},
        "fall-retargets-new-nearest-support-every-tick": {"position", "verticalVelocity", "viewport", "petHalfSize", "previousTarget", "newlyAvailableTarget", "targets", "expectedTarget", "expectedPositionAfterOneTick", "expectedVerticalVelocity", "expectedMode"},
        "fall-already-touching-support-lands": {"position", "mode", "verticalVelocity", "viewport", "petHalfSize", "target", "expectedPosition", "expectedTarget", "expectedMode", "expectedVerticalVelocity"},
        "synthetic-bottom-hard-landing-bounces-twice": {"position", "verticalVelocity", "viewport", "petHalfSize", "targets", "expectedTarget", "expectedSyntheticSupportY", "expectedPosition", "expectedImpactTimeSeconds", "expectedImpactVerticalVelocity", "expectedMode", "expectedBounceVerticalVelocity", "expectedBouncesRemaining"},
        "suspended-drag-release-enters-fall": {"position", "viewport", "petHalfSize", "targets", "releaseOnLegalSupport", "expectedMode", "expectedTarget", "expectedVerticalVelocity"},
        "center-bias-prefers-interior": {"position", "viewport", "targets", "expectedTarget"},
        "center-bias-measures-nearest-support": {"position", "viewport", "targets", "expectedTarget"},
    }
    for behavior in payload.get("behaviorVectors", []):
        name = behavior.get("name")
        missing = behavior_fields.get(name, set()) - behavior.keys()
        if missing:
            fail(f"Pet companion behavior vector {name} is missing fields: {sorted(missing)}")
    behavior_by_name = {item["name"]: item for item in payload["behaviorVectors"]}
    chart_reversal = behavior_by_name["chart-path-reverses"]
    if (
        float(chart_reversal["step"]) != 30.0
        or int(chart_reversal["ticks"]) != 20
        or chart_reversal.get("expectedMode") != "slide"
        or chart_reversal.get("mustReverse") is not True
    ):
        fail("Pet companion chart reversal vector must cover fixed curve acceleration and post-corner motion")

    def support_intersects_fall_ray(target: dict, position: list, pet_half_size: float) -> bool:
        rect = target["rect"]
        current_x = float(position[0])
        support_y = float(rect[1]) - pet_half_size
        return (
            support_y >= float(position[1])
            and float(rect[0]) - pet_half_size <= current_x <= float(rect[0]) + float(rect[2]) + pet_half_size
        )

    no_below = behavior_by_name["fall-without-below-target-uses-viewport-bottom"]
    viewport_bottom = float(no_below["viewport"][1])
    expected_support_y = viewport_bottom - float(no_below["petHalfSize"])
    fall_dt = float(payload["motion"]["fallTimeStepSeconds"])
    fall_gravity = float(payload["motion"]["fallGravityLogicalUnitsPerSecondSquared"])
    initial_velocity = float(no_below["verticalVelocity"])
    expected_next_y = float(no_below["position"][1]) + initial_velocity * fall_dt + 0.5 * fall_gravity * fall_dt * fall_dt
    expected_next_velocity = initial_velocity + fall_gravity * fall_dt
    if (
        no_below["expectedTarget"] is not None
        or no_below["expectedMode"] != "fall"
        or no_below["expectedYDirection"] != "nondecreasing"
        or not math.isclose(float(no_below["expectedSyntheticSupportY"]), expected_support_y)
        or not math.isclose(float(no_below["expectedPositionAfterOneTick"][0]), float(no_below["position"][0]))
        or not math.isclose(float(no_below["expectedPositionAfterOneTick"][1]), expected_next_y)
        or not math.isclose(float(no_below["expectedVerticalVelocity"]), expected_next_velocity)
        or any(
            support_intersects_fall_ray(target, no_below["position"], float(no_below["petHalfSize"]))
            for target in no_below["targets"]
        )
    ):
        fail("FALL without a legal below target must continue to the viewport bottom support")
    offset_fall = behavior_by_name["fall-skips-horizontally-offset-support"]
    legal_targets = [
        target
        for target in offset_fall["targets"]
        if support_intersects_fall_ray(target, offset_fall["position"], float(offset_fall["petHalfSize"]))
    ]
    nearest_legal = min(
        legal_targets,
        key=lambda target: float(target["rect"][1]) - float(offset_fall["petHalfSize"]),
        default=None,
    )
    offset_next_y = (
        float(offset_fall["position"][1])
        + float(offset_fall["verticalVelocity"]) * fall_dt
        + 0.5 * fall_gravity * fall_dt * fall_dt
    )
    if (
        nearest_legal is None
        or offset_fall["expectedTarget"] != nearest_legal["id"]
        or offset_fall["expectedMode"] != "fall"
        or not math.isclose(float(offset_fall["expectedPositionAfterOneTick"][0]), float(offset_fall["position"][0]))
        or not math.isclose(float(offset_fall["expectedPositionAfterOneTick"][1]), offset_next_y)
        or not math.isclose(
            float(offset_fall["expectedVerticalVelocity"]),
            float(offset_fall["verticalVelocity"]) + fall_gravity * fall_dt,
        )
        or not any(
            float(target["rect"][1]) - float(offset_fall["petHalfSize"]) >= float(offset_fall["position"][1])
            and not support_intersects_fall_ray(target, offset_fall["position"], float(offset_fall["petHalfSize"]))
            and float(target["rect"][1]) < float(nearest_legal["rect"][1])
            for target in offset_fall["targets"]
        )
    ):
        fail("FALL must skip horizontally offset supports and keep its x coordinate fixed")

    retarget_fall = behavior_by_name["fall-retargets-new-nearest-support-every-tick"]
    retarget_targets = {target["id"]: target for target in retarget_fall["targets"]}
    previous_target = retarget_targets.get(retarget_fall["previousTarget"])
    newly_available_target = retarget_targets.get(retarget_fall["newlyAvailableTarget"])
    retarget_legal = [
        target
        for target in retarget_fall["targets"]
        if support_intersects_fall_ray(target, retarget_fall["position"], float(retarget_fall["petHalfSize"]))
    ]
    nearest_retarget = min(
        retarget_legal,
        key=lambda target: float(target["rect"][1]) - float(retarget_fall["petHalfSize"]),
        default=None,
    )
    retarget_next_y = (
        float(retarget_fall["position"][1])
        + float(retarget_fall["verticalVelocity"]) * fall_dt
        + 0.5 * fall_gravity * fall_dt * fall_dt
    )
    if (
        previous_target is None
        or newly_available_target is None
        or previous_target not in retarget_legal
        or newly_available_target not in retarget_legal
        or nearest_retarget is None
        or retarget_fall["previousTarget"] == retarget_fall["expectedTarget"]
        or retarget_fall["newlyAvailableTarget"] != retarget_fall["expectedTarget"]
        or nearest_retarget["id"] != retarget_fall["expectedTarget"]
        or float(newly_available_target["rect"][1]) >= float(previous_target["rect"][1])
        or retarget_fall["expectedMode"] != "fall"
        or not math.isclose(float(retarget_fall["expectedPositionAfterOneTick"][0]), float(retarget_fall["position"][0]))
        or not math.isclose(float(retarget_fall["expectedPositionAfterOneTick"][1]), retarget_next_y)
        or not math.isclose(
            float(retarget_fall["expectedVerticalVelocity"]),
            float(retarget_fall["verticalVelocity"]) + fall_gravity * fall_dt,
        )
    ):
        fail("FALL must retarget every tick when a nearer support appears on the current x ray")

    touching_fall = behavior_by_name["fall-already-touching-support-lands"]
    touching_support_y = (
        float(touching_fall["target"]["rect"][1])
        - float(touching_fall["petHalfSize"])
    )
    if (
        touching_fall["mode"] != "fall"
        or not support_intersects_fall_ray(
            touching_fall["target"],
            touching_fall["position"],
            float(touching_fall["petHalfSize"]),
        )
        or not math.isclose(touching_support_y, float(touching_fall["position"][1]))
        or touching_fall["expectedPosition"] != touching_fall["position"]
        or touching_fall["expectedTarget"] != touching_fall["target"]["id"]
        or touching_fall["expectedMode"] != "idle"
        or float(touching_fall["verticalVelocity"]) >= float(payload["motion"]["hardLandingSpeed"])
        or float(touching_fall["expectedVerticalVelocity"]) != 0.0
    ):
        fail("FALL already touching a legal support must land without penetrating it")

    def verify_hard_landing(vector: dict, support_y: float) -> None:
        start_y = float(vector["position"][1])
        initial_velocity = float(vector["verticalVelocity"])
        distance = support_y - start_y
        if distance < 0:
            fail(f"Pet companion landing vector {vector['name']} has support above its position")
        impact_velocity = math.sqrt(initial_velocity * initial_velocity + 2.0 * fall_gravity * distance)
        impact_time = (impact_velocity - initial_velocity) / fall_gravity
        if impact_time < 0 or impact_time > fall_dt:
            fail(f"Pet companion landing vector {vector['name']} does not collide within one tick")
        if (
            not math.isclose(float(vector["expectedPosition"][0]), float(vector["position"][0]))
            or not math.isclose(float(vector["expectedPosition"][1]), support_y)
            or not math.isclose(float(vector["expectedImpactTimeSeconds"]), impact_time, rel_tol=1e-12, abs_tol=1e-12)
            or not math.isclose(float(vector["expectedImpactVerticalVelocity"]), impact_velocity, rel_tol=1e-12, abs_tol=1e-9)
            or impact_velocity < float(payload["motion"]["hardLandingSpeed"])
            or vector["expectedMode"] != "bounce"
            or not math.isclose(float(vector["expectedBounceVerticalVelocity"]), -float(payload["motion"]["firstBounceSpeed"]))
            or int(vector["expectedBouncesRemaining"]) != int(payload["motion"]["bounceCount"])
        ):
            fail(f"Pet companion landing vector {vector['name']} differs from the hard-landing rule")

    hard_landing = behavior_by_name["hard-landing-bounces-twice"]
    verify_hard_landing(hard_landing, float(hard_landing["target"]["rect"][1]))
    synthetic_landing = behavior_by_name["synthetic-bottom-hard-landing-bounces-twice"]
    synthetic_support_y = float(synthetic_landing["viewport"][1]) - float(synthetic_landing["petHalfSize"])
    if (
        synthetic_landing["targets"] != []
        or synthetic_landing["expectedTarget"] is not None
        or not math.isclose(float(synthetic_landing["expectedSyntheticSupportY"]), synthetic_support_y)
    ):
        fail("Synthetic viewport-bottom landing vector does not use the viewport support")
    verify_hard_landing(synthetic_landing, synthetic_support_y)
    suspended_release = behavior_by_name["suspended-drag-release-enters-fall"]
    if (
        suspended_release["releaseOnLegalSupport"] is not False
        or suspended_release["expectedMode"] != "fall"
        or suspended_release["expectedTarget"] is not None
        or float(suspended_release["expectedVerticalVelocity"]) != 0.0
    ):
        fail("Suspended drag release must begin a fresh targetless FALL")
    drag_release = next((item for item in payload["vectors"] if item.get("name") == "drag-release"), None)
    if drag_release is None or drag_release.get("releaseOnLegalSupport") is not True or drag_release.get("expectedMode") != "idle":
        fail("Drag release on legal support must enter IDLE")

    drag_velocity_vectors = payload.get("dragVelocityVectors", [])
    if {item.get("name") for item in drag_velocity_vectors} != {
        "terminal-tangent-estimate-uses-constrained-centres",
        "insufficient-drag-samples-do-not-fling",
    }:
        fail("Pet companion drag velocity vectors differ")
    for vector in drag_velocity_vectors:
        samples = vector.get("samples", [])
        timestamps = [float(sample.get("timeMs", -1)) for sample in samples]
        if timestamps != sorted(timestamps) or any(later <= earlier for earlier, later in zip(timestamps, timestamps[1:])):
            fail(f"Pet companion drag velocity vector {vector['name']} has non-monotonic samples")
        expected_velocity = [float(value) for value in vector["expectedVelocity"]]
        if len(samples) < 2:
            if expected_velocity != [0.0, 0.0] or vector.get("expectedMode") != "fall":
                fail("Insufficient drag samples must produce a targetless FALL")
            continue
        # For a linear trajectory, weighted terminal regression must recover
        # the same tangent exactly regardless of the positive time weights.
        first = samples[0]
        last = samples[-1]
        elapsed_ms = float(last["timeMs"]) - float(first["timeMs"])
        if elapsed_ms <= 0:
            fail(f"Pet companion drag velocity vector {vector['name']} has zero duration")
        expected_from_endpoints = [
            (float(last["position"][axis]) - float(first["position"][axis])) * 1000.0 / elapsed_ms
            for axis in (0, 1)
        ]
        if any(not math.isclose(actual, wanted, rel_tol=1e-12, abs_tol=1e-9) for actual, wanted in zip(expected_velocity, expected_from_endpoints)):
            fail(f"Pet companion drag velocity vector {vector['name']} has the wrong terminal tangent")
        if vector.get("expectedMode") != "fling" or not math.isclose(
            float(vector.get("expectedSpeed", math.hypot(*expected_velocity))),
            math.hypot(*expected_velocity),
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            fail(f"Pet companion drag velocity vector {vector['name']} does not enter FLING")

    motion = payload["motion"]
    dt = float(motion["fallTimeStepSeconds"])
    gravity = float(motion["fallGravityLogicalUnitsPerSecondSquared"])
    physics_vectors = payload.get("fallPhysicsVectors", [])
    if {item.get("name") for item in physics_vectors} != {"closed-form-constant-acceleration-consecutive-ticks"}:
        fail("Pet companion fixed-step fall physics vector differs")
    for vector in physics_vectors:
        initial_y = float(vector["initialPositionY"])
        initial_velocity = float(vector["initialVerticalVelocity"])
        samples = vector.get("samples", [])
        if len(samples) < 3 or [sample.get("tick") for sample in samples] != list(range(1, len(samples) + 1)):
            fail(f"Pet companion physics vector {vector['name']} must contain consecutive ticks")
        previous_y = initial_y
        displacements = []
        for sample in samples:
            tick = int(sample["tick"])
            elapsed = tick * dt
            expected_y = initial_y + initial_velocity * elapsed + 0.5 * gravity * elapsed * elapsed
            expected_velocity = initial_velocity + gravity * elapsed
            observed_y = float(sample["expectedY"])
            observed_velocity = float(sample["expectedVerticalVelocity"])
            observed_displacement = float(sample["expectedTickDisplacement"])
            if not math.isclose(float(sample["elapsedSeconds"]), elapsed, rel_tol=1e-12, abs_tol=1e-12):
                fail(f"Pet companion physics vector {vector['name']} has the wrong elapsed time at tick {tick}")
            if not math.isclose(observed_y, expected_y, rel_tol=1e-12, abs_tol=1e-9):
                fail(f"Pet companion physics vector {vector['name']} has the wrong position at tick {tick}")
            if not math.isclose(observed_velocity, expected_velocity, rel_tol=1e-12, abs_tol=1e-9):
                fail(f"Pet companion physics vector {vector['name']} has the wrong velocity at tick {tick}")
            displacement = observed_y - previous_y
            if not math.isclose(observed_displacement, displacement, rel_tol=1e-12, abs_tol=1e-9):
                fail(f"Pet companion physics vector {vector['name']} has the wrong displacement at tick {tick}")
            if displacement < 0:
                fail(f"Pet companion physics vector {vector['name']} moves upward during FALL")
            displacements.append(displacement)
            previous_y = observed_y
        if any(later <= earlier for earlier, later in zip(displacements, displacements[1:])):
            fail(f"Pet companion physics vector {vector['name']} does not accelerate downward")
        expected_second_difference = gravity * dt * dt
        second_differences = [later - earlier for earlier, later in zip(displacements, displacements[1:])]
        if any(not math.isclose(value, expected_second_difference, rel_tol=1e-12, abs_tol=1e-9) for value in second_differences):
            fail(f"Pet companion physics vector {vector['name']} does not follow square-time displacement")

    # Fling vectors share the same constant-acceleration convention as FALL,
    # but retain both velocity components and may start with an upward y speed.
    fling_vectors = payload.get("flingPhysicsVectors", [])
    expected_fling_names = {
        "diagonal-release-preserves-tangent-and-gravity",
        "release-speed-vector-is-limited-proportionally",
        "high-speed-tick-uses-deterministic-substeps",
        "sloped-chart-contact-uses-relative-descending-derivative",
    }
    if {item.get("name") for item in fling_vectors} != expected_fling_names:
        fail("Pet companion fling physics vectors differ")
    for vector in fling_vectors:
        if vector["name"] == "diagonal-release-preserves-tangent-and-gravity":
            position = vector["releasePosition"]
            velocity = vector["releaseVelocity"]
            step = float(vector["stepSeconds"])
            gravity = float(motion["flingGravityLogicalUnitsPerSecondSquared"])
            previous = [float(position[0]), float(position[1])]
            for sample in vector["samples"]:
                tick = int(sample["tick"])
                elapsed = tick * step
                expected = [
                    float(position[0]) + float(velocity[0]) * elapsed,
                    float(position[1]) + float(velocity[1]) * elapsed + 0.5 * gravity * elapsed * elapsed,
                ]
                expected_velocity = [float(velocity[0]), float(velocity[1]) + gravity * elapsed]
                observed = [float(value) for value in sample["expectedPosition"]]
                observed_velocity = [float(value) for value in sample["expectedVelocity"]]
                if any(not math.isclose(actual, wanted, rel_tol=1e-12, abs_tol=1e-9) for actual, wanted in zip(observed, expected)):
                    fail(f"Pet companion fling vector {vector['name']} has the wrong position at tick {tick}")
                if any(not math.isclose(actual, wanted, rel_tol=1e-12, abs_tol=1e-9) for actual, wanted in zip(observed_velocity, expected_velocity)):
                    fail(f"Pet companion fling vector {vector['name']} has the wrong velocity at tick {tick}")
                # The first samples intentionally remain on the upward arc;
                # this catches accidental sign inversion of vx/vy.
                if observed[0] <= previous[0] or (tick == 1 and observed[1] >= previous[1]):
                    fail(f"Pet companion fling vector {vector['name']} loses its terminal tangent")
                previous = observed
        elif vector["name"] == "release-speed-vector-is-limited-proportionally":
            release = [float(value) for value in vector["releaseVelocity"]]
            maximum = float(vector["maxFlingSpeed"])
            magnitude = math.hypot(*release)
            expected = [component * maximum / magnitude for component in release]
            observed = [float(value) for value in vector["expectedVelocity"]]
            if not math.isclose(float(vector["expectedMagnitude"]), maximum, rel_tol=1e-12, abs_tol=1e-9):
                fail("Pet companion fling speed limit vector has the wrong magnitude")
            if any(not math.isclose(actual, wanted, rel_tol=1e-12, abs_tol=1e-9) for actual, wanted in zip(observed, expected)):
                fail("Pet companion fling speed must be limited proportionally")
        elif vector["name"] == "high-speed-tick-uses-deterministic-substeps":
            step = float(vector["stepSeconds"])
            max_substep = float(vector["maxSubstepSeconds"])
            max_substeps = int(vector["maxSubstepsPerTick"])
            expected_substeps = math.ceil(step / max_substep)
            if expected_substeps > max_substeps or int(vector["expectedSubsteps"]) != expected_substeps:
                fail("Pet companion high-speed tick exceeds deterministic substep budget")
            initial = vector.get("initialPosition", [0.0, 0.0])
            velocity = vector["releaseVelocity"]
            gravity = float(motion["flingGravityLogicalUnitsPerSecondSquared"])
            expected_position = [
                float(initial[0]) + float(velocity[0]) * step,
                float(initial[1]) + float(velocity[1]) * step + 0.5 * gravity * step * step,
            ]
            expected_velocity = [float(velocity[0]), float(velocity[1]) + gravity * step]
            if any(not math.isclose(float(actual), wanted, rel_tol=1e-12, abs_tol=1e-9) for actual, wanted in zip(vector["expectedPosition"], expected_position)):
                fail("Pet companion high-speed substep position differs from closed-form integration")
            if any(not math.isclose(float(actual), wanted, rel_tol=1e-12, abs_tol=1e-9) for actual, wanted in zip(vector["expectedVelocity"], expected_velocity)):
                fail("Pet companion high-speed substep velocity differs from closed-form integration")
        else:
            initial = [float(value) for value in vector["initialPosition"]]
            velocity = [float(value) for value in vector["releaseVelocity"]]
            segment = [[float(value) for value in point] for point in vector["chartSegment"]]
            if len(segment) != 2 or len(segment[0]) != 2 or len(segment[1]) != 2:
                fail("Pet companion sloped-chart vector must contain one finite segment")
            delta_x = segment[1][0] - segment[0][0]
            if abs(delta_x) <= 1e-12:
                fail("Pet companion sloped-chart derivative vector cannot use a vertical segment")
            slope = (segment[1][1] - segment[0][1]) / delta_x
            intercept = segment[0][1] - slope * segment[0][0]
            step = float(vector["stepSeconds"])
            gravity = float(motion["flingGravityLogicalUnitsPerSecondSquared"])
            a = 0.5 * gravity
            b = velocity[1] - slope * velocity[0]
            c = initial[1] - slope * initial[0] - intercept
            discriminant = b * b - 4.0 * a * c
            if discriminant < 0.0:
                fail("Pet companion sloped-chart vector has no contact root")
            root_discriminant = math.sqrt(discriminant)
            roots = sorted(((-b - root_discriminant) / (2.0 * a), (-b + root_discriminant) / (2.0 * a)))
            valid_contacts = []
            minimum_x, maximum_x = sorted((segment[0][0], segment[1][0]))
            for root in roots:
                if root < -1e-12 or root > step + 1e-12:
                    continue
                root = max(0.0, min(step, root))
                contact_x = initial[0] + velocity[0] * root
                derivative = b + 2.0 * a * root
                if minimum_x - 1e-9 <= contact_x <= maximum_x + 1e-9 and derivative >= -1e-9:
                    valid_contacts.append((root, contact_x, derivative))
            if not valid_contacts:
                fail("Pet companion sloped-chart vector has no relative descending contact")
            contact_time, contact_x, derivative = valid_contacts[0]
            contact_y = initial[1] + velocity[1] * contact_time + a * contact_time * contact_time
            world_vertical_velocity = velocity[1] + gravity * contact_time
            if vector.get("contactEquation") != "y(t)-(slope*x(t)+intercept)" or vector.get("contactDirection") != "derivative-nonnegative":
                fail("Pet companion sloped-chart vector uses the wrong contact equation")
            if not math.isclose(float(vector["expectedContactTimeSeconds"]), contact_time, rel_tol=1e-12, abs_tol=1e-12):
                fail("Pet companion sloped-chart vector has the wrong contact time")
            expected_contact = [float(value) for value in vector["expectedContactPoint"]]
            if not math.isclose(expected_contact[0], contact_x, rel_tol=1e-12, abs_tol=1e-9) or not math.isclose(expected_contact[1], contact_y, rel_tol=1e-12, abs_tol=1e-9):
                fail("Pet companion sloped-chart vector has the wrong contact point")
            if not math.isclose(contact_y, slope * contact_x + intercept, rel_tol=1e-12, abs_tol=1e-9):
                fail("Pet companion sloped-chart contact does not lie on the segment")
            if not math.isclose(float(vector["expectedWorldVerticalVelocity"]), world_vertical_velocity, rel_tol=1e-12, abs_tol=1e-9):
                fail("Pet companion sloped-chart vector has the wrong world vertical velocity")
            if not math.isclose(float(vector["expectedContactEquationDerivative"]), derivative, rel_tol=1e-12, abs_tol=1e-9):
                fail("Pet companion sloped-chart vector has the wrong contact derivative")
            if (
                world_vertical_velocity >= 0.0
                or derivative <= 0.0
                or vector.get("expectedWorldVerticalDirection") != "up"
                or vector.get("expectedRelativeDirection") != "descending"
            ):
                fail("Pet companion sloped-chart vector does not distinguish world and relative direction")
            expected_mode = "bounce" if abs(world_vertical_velocity) >= float(motion["hardLandingSpeed"]) else "idle"
            if vector.get("expectedMode") != expected_mode:
                fail("Pet companion sloped-chart vector has the wrong landing mode")

    curve_vectors = payload.get("curveMotionVectors", [])
    if {item.get("name") for item in curve_vectors} != {
        "curve-slide-accelerates-from-rest",
        "curve-slide-retains-budget-across-corner",
        "curve-slide-step-override-keeps-contract-acceleration-and-corner-budget",
    }:
        fail("Pet companion curve motion vectors differ")
    for vector in curve_vectors:
        acceleration = float(vector["curveAcceleration"])
        cruise = float(vector["cruiseSpeed"])
        if not math.isclose(acceleration, float(motion["curveAcceleration"]), rel_tol=0.0, abs_tol=1e-12):
            fail(f"Pet companion curve vector {vector['name']} changes the contract acceleration")
        if vector["name"] == "curve-slide-accelerates-from-rest":
            speeds = [float(value) for value in vector["tickSpeeds"]]
            expected = [min(cruise, acceleration * (index + 1)) for index in range(len(speeds))]
            if any(not math.isclose(actual, wanted, rel_tol=1e-12, abs_tol=1e-9) for actual, wanted in zip(speeds, expected)):
                fail("Pet companion chart sliding must accelerate from rest")
            if vector.get("expectedMode") != "slide" or any(later <= earlier for earlier, later in zip(speeds, speeds[1:])):
                fail("Pet companion chart sliding acceleration vector is invalid")
        elif vector["name"] == "curve-slide-retains-budget-across-corner":
            current = float(vector["initialMovementSpeed"])
            speed = min(cruise, current + acceleration)
            budget = speed
            remaining = float(vector["remainingToCorner"])
            expected_budget = budget - remaining
            if (
                not math.isclose(float(vector["expectedSpeedAfterCorner"]), speed, rel_tol=1e-12, abs_tol=1e-9)
                or not math.isclose(float(vector["expectedBudgetAfterCorner"]), expected_budget, rel_tol=1e-12, abs_tol=1e-9)
                or expected_budget <= 0
                or vector.get("expectedMode") != "slide"
            ):
                fail("Pet companion chart sliding must retain speed budget across corners")
        else:
            current = float(vector["initialMovementSpeed"])
            requested_step = float(vector["requestedStep"])
            if requested_step <= cruise:
                fail("Pet companion curve step-invariance vector must exceed the normal cruise step")
            speed = min(requested_step, current + acceleration)
            remaining = float(vector["remainingToCorner"])
            expected_budget = speed - remaining
            if (
                not math.isclose(float(vector["expectedSpeedAfterCorner"]), speed, rel_tol=1e-12, abs_tol=1e-9)
                or not math.isclose(float(vector["expectedBudgetAfterCorner"]), expected_budget, rel_tol=1e-12, abs_tol=1e-9)
                or expected_budget <= 0.0
                or vector.get("expectedMode") != "slide"
            ):
                fail("Pet companion curve step override changes acceleration or loses corner budget")

    curve_landing_vectors = payload.get("curveLandingVectors", [])
    if {item.get("name") for item in curve_landing_vectors} != {
        "vertical-fall-projects-onto-descending-tangent",
        "zero-speed-mid-segment-starts-downhill-without-vertex-snap",
        "uphill-fling-slows-before-reversing-downhill",
        "vertical-fall-uses-reverse-order-downhill-on-ascending-segment",
        "flat-segment-rest-uses-registration-direction",
        "fling-projection-clamps-uphill-speed",
    }:
        fail("Pet companion curve landing vectors differ")
    response = float(motion["curveDownhillResponsePerTick"])
    terminal_speed = float(motion["curveDownhillTerminalSpeed"])
    landing_limit = float(motion["curveLandingSpeedLimit"])
    direction_epsilon = float(motion["curveDirectionEpsilon"])
    tick_seconds = float(payload["tickMs"]) / 1000.0
    for vector in curve_landing_vectors:
        start, end = vector["segment"]
        dx = float(end[0]) - float(start[0])
        dy = float(end[1]) - float(start[1])
        length = math.hypot(dx, dy)
        if length <= 1e-12:
            fail(f"Pet companion curve landing vector {vector['name']} has a degenerate segment")
        tangent = (dx / length, dy / length)
        expected_tangent = vector.get("expectedUnitTangent")
        if expected_tangent is not None and any(
            not math.isclose(float(actual), wanted, rel_tol=1e-12, abs_tol=1e-12)
            for actual, wanted in zip(expected_tangent, tangent)
        ):
            fail(f"Pet companion curve landing vector {vector['name']} has the wrong tangent")
        incoming = [float(value) for value in vector["incomingVelocity"]]
        projected = (incoming[0] * tangent[0] + incoming[1] * tangent[1]) * tick_seconds
        projected = max(-landing_limit, min(landing_limit, projected))
        if abs(projected) <= direction_epsilon:
            projected = 0.0
        initial = float(vector["expectedInitialCurveVelocity"])
        if not math.isclose(initial, projected, rel_tol=1e-12, abs_tol=1e-9):
            fail(f"Pet companion curve landing vector {vector['name']} has the wrong projected speed")
        downhill_direction = (
            1 if tangent[1] > direction_epsilon
            else -1 if tangent[1] < -direction_epsilon
            else 1
        )
        expected_direction = (
            1 if initial > direction_epsilon
            else -1 if initial < -direction_epsilon
            else downhill_direction
        )
        if int(vector["expectedPathDirection"]) != expected_direction:
            fail(f"Pet companion curve landing vector {vector['name']} has the wrong initial direction")
        if (
            vector["name"] == "flat-segment-rest-uses-registration-direction"
            and int(vector.get("initialPathDirection", 1)) != -1
        ):
            fail("Pet companion flat curve vector does not guard against stale reverse direction")
        terminal = downhill_direction * terminal_speed
        next_velocity = initial + (terminal - initial) * response
        if not math.isclose(
            float(vector["expectedNextCurveVelocity"]),
            next_velocity,
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            fail(f"Pet companion curve landing vector {vector['name']} has the wrong relaxed speed")
        expected_position = vector.get("expectedNextPosition")
        if expected_position is not None:
            contact = [float(value) for value in vector["contactPoint"]]
            next_position = (
                contact[0] + tangent[0] * next_velocity,
                contact[1] + tangent[1] * next_velocity,
            )
            if any(
                not math.isclose(float(actual), wanted, rel_tol=1e-12, abs_tol=1e-9)
                for actual, wanted in zip(expected_position, next_position)
            ):
                fail(f"Pet companion curve landing vector {vector['name']} snaps away from its contact segment")
        if vector.get("expectedMode") != "slide":
            fail(f"Pet companion curve landing vector {vector['name']} must enter slide")
        downhill_tick = vector.get("expectedDownhillByTick")
        if downhill_tick is not None:
            velocity = initial
            first_positive_tick = None
            for tick in range(1, int(downhill_tick) + 1):
                velocity += (terminal - velocity) * response
                if velocity > 0.0 and first_positive_tick is None:
                    first_positive_tick = tick
            if first_positive_tick != int(downhill_tick):
                fail("Pet companion uphill curve landing reverses on the wrong tick")

    curve_scale_vectors = payload.get("curveScaleVectors", [])
    if {item.get("name") for item in curve_scale_vectors} != {
        "density-two-preserves-logical-curve-motion",
    }:
        fail("Pet companion curve scale vectors differ")
    for vector in curve_scale_vectors:
        scale = float(vector["unitScale"])
        if scale <= 1.0:
            fail("Pet companion curve scale vector must exercise a non-unit coordinate scale")
        start, end = vector["logicalSegment"]
        dx = float(end[0]) - float(start[0])
        dy = float(end[1]) - float(start[1])
        length = math.hypot(dx, dy)
        tangent = (dx / length, dy / length)
        incoming = [float(value) for value in vector["logicalIncomingVelocity"]]
        initial = (incoming[0] * tangent[0] + incoming[1] * tangent[1]) * tick_seconds
        initial = max(-landing_limit, min(landing_limit, initial))
        if abs(initial) <= direction_epsilon:
            initial = 0.0
        expected_initial = float(vector["expectedInitialLogicalCurveVelocity"])
        if not math.isclose(expected_initial, initial, rel_tol=1e-12, abs_tol=1e-9):
            fail("Pet companion scaled curve projection changes logical velocity")
        downhill = (
            1 if tangent[1] > direction_epsilon
            else -1 if tangent[1] < -direction_epsilon
            else 1
        )
        next_velocity = initial + (downhill * terminal_speed - initial) * response
        if not math.isclose(
            float(vector["expectedNextLogicalCurveVelocity"]),
            next_velocity,
            rel_tol=1e-12,
            abs_tol=1e-9,
        ):
            fail("Pet companion scaled curve relaxation changes logical velocity")
        contact = [float(value) for value in vector["logicalContactPoint"]]
        expected_physical = (
            (contact[0] + tangent[0] * next_velocity) * scale,
            (contact[1] + tangent[1] * next_velocity) * scale,
        )
        if any(
            not math.isclose(float(actual), wanted, rel_tol=1e-12, abs_tol=1e-8)
            for actual, wanted in zip(vector["expectedNextPhysicalPosition"], expected_physical)
        ) or vector.get("expectedMode") != "slide":
            fail("Pet companion curve path budget does not restore the physical coordinate scale")

    curve_endpoint_vectors = payload.get("curveEndpointVectors", [])
    if {item.get("name") for item in curve_endpoint_vectors} != {
        "flat-uphill-endpoint-stops-and-reverses-downhill",
        "near-horizontal-uphill-endpoint-uses-unit-tangent",
    }:
        fail("Pet companion curve endpoint vectors differ")
    for vector in curve_endpoint_vectors:
        start, end = vector["segment"]
        dx = float(end[0]) - float(start[0])
        dy = float(end[1]) - float(start[1])
        length = math.hypot(dx, dy)
        tangent = (dx / length, dy / length)
        downhill = (
            1 if tangent[1] > direction_epsilon
            else -1 if tangent[1] < -direction_epsilon
            else 1
        )
        direction = -1 if int(vector["initialPathDirection"]) < 0 else 1
        velocity = float(vector["initialCurveVelocity"])
        initial_position = [float(value) for value in vector["initialPosition"]]
        arc_position = (
            (initial_position[0] - float(start[0])) * tangent[0]
            + (initial_position[1] - float(start[1])) * tangent[1]
        )
        reached_tick = None
        endpoint_arc = 0.0 if direction < 0 else length
        for tick in range(1, int(vector["expectedEndpointTick"]) + 1):
            velocity += (downhill * terminal_speed - velocity) * response
            next_arc = arc_position + velocity
            if (direction < 0 and next_arc <= endpoint_arc) or (
                direction > 0 and next_arc >= endpoint_arc
            ):
                reached_tick = tick
                break
            arc_position = next_arc
        if reached_tick != int(vector["expectedEndpointTick"]):
            fail(f"Pet companion curve endpoint vector {vector['name']} reaches on the wrong tick")
        endpoint_position = (
            float(start[0]) + tangent[0] * endpoint_arc,
            float(start[1]) + tangent[1] * endpoint_arc,
        )
        if any(
            not math.isclose(float(actual), wanted, rel_tol=1e-12, abs_tol=1e-8)
            for actual, wanted in zip(vector["expectedEndpointPosition"], endpoint_position)
        ):
            fail(f"Pet companion curve endpoint vector {vector['name']} has the wrong endpoint")
        if (
            direction == downhill
            or float(vector["expectedEndpointCurveVelocity"]) != 0.0
            or int(vector["expectedEndpointPathDirection"]) != downhill
            or vector.get("expectedEndpointMode") != "slide"
        ):
            fail(f"Pet companion curve endpoint vector {vector['name']} does not stop and reverse")
        next_velocity = downhill * terminal_speed * response
        next_position = (
            endpoint_position[0] + tangent[0] * next_velocity,
            endpoint_position[1] + tangent[1] * next_velocity,
        )
        if (
            not math.isclose(float(vector["expectedNextCurveVelocity"]), next_velocity, abs_tol=1e-9)
            or any(
                not math.isclose(float(actual), wanted, rel_tol=1e-12, abs_tol=1e-8)
                for actual, wanted in zip(vector["expectedNextPosition"], next_position)
            )
            or vector.get("expectedNextMode") != "slide"
        ):
            fail(f"Pet companion curve endpoint vector {vector['name']} resumes downhill incorrectly")

    contract_text = contract_path.read_text(encoding="utf-8")
    for marker in (
        "dot(V_hit,T)*dt",
        "u_next=u+(u_terminal-u)*0.0625",
        "不得用“最近顶点”",
        "物理单位比例",
        "归一化单位切线",
        "单个帧错误",
        "释放指针捕获",
    ):
        if marker not in contract_text:
            fail(f"Pet companion curve landing contract is missing {marker}")
    windows_pet_source = (ROOT / "windows" / "domain" / "pet_companion.py").read_text(encoding="utf-8")
    android_pet_source = (
        ROOT / "android" / "domain" / "src" / "main" / "kotlin" /
        "com" / "lexitrack" / "learning" / "domain" / "PetCompanion.kt"
    ).read_text(encoding="utf-8")
    windows_tree = ast.parse(windows_pet_source)
    windows_functions = {
        node.name: node
        for node in windows_tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    windows_constants: dict[str, float] = {}
    for node in windows_tree.body:
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, (int, float))
        ):
            windows_constants[node.targets[0].id] = float(node.value.value)
    expected_windows_constants = {
        "CURVE_LANDING_SPEED_LIMIT": landing_limit,
        "CURVE_DOWNHILL_TERMINAL_SPEED": terminal_speed,
        "CURVE_DOWNHILL_RESPONSE_PER_TICK": response,
        "CURVE_DIRECTION_EPSILON": direction_epsilon,
    }
    for name, expected in expected_windows_constants.items():
        actual = windows_constants.get(name)
        if actual is None or not math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-12):
            fail(f"Windows curve landing constant {name} differs from the contract")

    def verify_windows_helper(name: str, constants: set[str], calls: set[str]) -> None:
        function = windows_functions.get(name)
        if function is None:
            fail(f"Windows curve landing helper {name} is missing")
        used_names = {node.id for node in ast.walk(function) if isinstance(node, ast.Name)}
        used_calls = {
            node.func.id
            for node in ast.walk(function)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        if not constants <= used_names:
            fail(f"Windows curve landing helper {name} is not wired to its contract constants")
        if not calls <= used_calls:
            fail(f"Windows curve landing helper {name} does not call its direction helper")

    direction_helper = windows_functions.get("_curve_downhill_direction")
    if direction_helper is None or len(direction_helper.args.args) != 1:
        fail("Windows curve downhill helper must derive flat direction without fallback state")
    verify_windows_helper(
        "_curve_downhill_direction",
        {"CURVE_DIRECTION_EPSILON"},
        set(),
    )
    endpoint_helper = windows_functions.get("_curve_endpoint_is_downhill")
    if endpoint_helper is None or len(endpoint_helper.args.args) != 3:
        fail("Windows curve endpoint helper must compare normalized local downhill direction")
    verify_windows_helper(
        "_curve_endpoint_is_downhill",
        {"CURVE_DIRECTION_EPSILON"},
        {"_curve_downhill_direction"},
    )
    verify_windows_helper(
        "_chart_landing_state",
        {"FALL_TIME_STEP_SECONDS", "CURVE_LANDING_SPEED_LIMIT", "CURVE_DIRECTION_EPSILON"},
        {"_curve_downhill_direction"},
    )
    verify_windows_helper(
        "_advance_landed_chart",
        {
            "CURVE_LANDING_SPEED_LIMIT",
            "CURVE_DOWNHILL_TERMINAL_SPEED",
            "CURVE_DOWNHILL_RESPONSE_PER_TICK",
            "CURVE_DIRECTION_EPSILON",
        },
        {"_curve_downhill_direction", "_curve_endpoint_is_downhill"},
    )
    verify_windows_helper("_advance_chart", set(), {"_curve_downhill_direction"})

    expected_android_constants = {
        "PET_CURVE_LANDING_SPEED_LIMIT": landing_limit,
        "PET_CURVE_DOWNHILL_TERMINAL_SPEED": terminal_speed,
        "PET_CURVE_DOWNHILL_RESPONSE_PER_TICK": response,
        "PET_CURVE_DIRECTION_EPSILON": direction_epsilon,
    }
    for name, expected in expected_android_constants.items():
        match = re.search(
            rf"(?m)^(?:private\s+)?const val {name}\s*=\s*([0-9.eE+-]+)f?\s*$",
            android_pet_source,
        )
        if match is None or not math.isclose(float(match.group(1)), expected, rel_tol=0.0, abs_tol=1e-12):
            fail(f"Android curve landing constant {name} differs from the contract")

    def android_helper_source(name: str) -> str:
        match = re.search(
            rf"(?ms)^private fun {name}\(.*?(?=^private (?:fun|data class)|\Z)",
            android_pet_source,
        )
        if match is None:
            fail(f"Android curve landing helper {name} is missing")
        return match.group(0)

    android_direction = android_helper_source("curveDownhillDirection")
    if (
        not re.search(r"curveDownhillDirection\(\s*unitTangent:\s*PetPoint\s*\)", android_direction)
        or "PET_CURVE_DIRECTION_EPSILON" not in android_direction
    ):
        fail("Android curve downhill helper must derive flat direction without fallback state")
    android_endpoint = android_helper_source("curveEndpointIsDownhill")
    if (
        "PET_CURVE_DIRECTION_EPSILON" not in android_endpoint
        or not re.search(r"curveDownhillDirection\(\s*unitTangent\s*\)", android_endpoint)
    ):
        fail("Android curve endpoint helper must compare normalized local downhill direction")
    android_landing = android_helper_source("chartLandingState")
    if (
        not {
            "PET_FALL_TIME_STEP_SECONDS",
            "PET_CURVE_LANDING_SPEED_LIMIT",
            "PET_CURVE_DIRECTION_EPSILON",
        } <= set(re.findall(r"\b[A-Z][A-Z0-9_]+\b", android_landing))
        or not re.search(r"curveDownhillDirection\(\s*segment\.unitTangent\s*\)", android_landing)
        or not re.search(r"PET_FALL_TIME_STEP_SECONDS\s*/\s*unitScale", android_landing)
    ):
        fail("Android chart landing helper is not wired to its contract constants and direction helper")
    android_advance = android_helper_source("advanceLandedChart")
    if (
        not {
            "PET_CURVE_LANDING_SPEED_LIMIT",
            "PET_CURVE_DOWNHILL_TERMINAL_SPEED",
            "PET_CURVE_DOWNHILL_RESPONSE_PER_TICK",
            "PET_CURVE_DIRECTION_EPSILON",
        } <= set(re.findall(r"\b[A-Z][A-Z0-9_]+\b", android_advance))
        or not re.search(r"curveDownhillDirection\(\s*segment\.unitTangent\s*\)", android_advance)
        or not re.search(r"abs\(curveVelocity\)\s*\*\s*unitScale", android_advance)
        or not re.search(r"curveEndpointIsDownhill\(\s*path,\s*endpoint,\s*direction\s*\)", android_advance)
    ):
        fail("Android landed chart helper is not wired to its contract constants and direction helper")
    if not re.search(
        r"curveDownhillDirection\(\s*segment\.unitTangent\s*\)",
        android_helper_source("advanceChart"),
    ):
        fail("Android autonomous chart helper does not use the shared downhill direction rule")

    migration_vectors = payload.get("windowMigrationVectors", [])
    if {item.get("name") for item in migration_vectors} != {
        "fling-exits-right-and-enters-neighbor",
        "fall-enters-new-window-from-top",
        "drag-crosses-left-into-new-window",
    }:
        fail("Pet companion window migration vectors differ")
    for vector in migration_vectors:
        source = vector["sourceWindow"]["rect"]
        target = vector["targetWindow"]["rect"]
        half = float(vector["petHalfSize"])
        direction = vector["entryDirection"]
        expected_host = vector["targetWindow"]["id"]
        if vector.get("expectedHost") != expected_host or vector.get("preserveGrabOffset") is not True:
            fail(f"Pet companion migration vector {vector['name']} loses host or grab state")
        if direction == "left":
            expected_x = half
            if vector.get("sourceExitEdge") != "right" or vector.get("targetEntryEdge") != "left":
                fail("Right-to-left pet window migration edges are inconsistent")
        elif direction == "right":
            expected_x = float(target[2]) - half
            if vector.get("sourceExitEdge") != "left" or vector.get("targetEntryEdge") != "right":
                fail("Left-to-right pet window migration edges are inconsistent")
        elif direction == "top":
            expected_x = min(
                max(
                    float(vector["positionInSource"][0]) - float(target[0]),
                    half,
                ),
                float(target[2]) - half,
            )
            if vector.get("sourceExitEdge") != "bottom" or vector.get("targetEntryEdge") != "top":
                fail("Top-entry pet window migration edges are inconsistent")
        else:
            fail(f"Pet companion migration vector {vector['name']} has an unknown direction")
        observed = vector["expectedPositionInTarget"]
        if not math.isclose(float(observed[0]), expected_x, rel_tol=1e-12, abs_tol=1e-9):
            fail(f"Pet companion migration vector {vector['name']} maps the x coordinate incorrectly")
        world_y = float(source[1]) + float(vector["positionInSource"][1])
        if direction in {"left", "right"}:
            expected_y = min(
                max(world_y, float(target[1]) + half),
                float(target[1]) + float(target[3]) - half,
            ) - float(target[1])
        else:
            expected_y = -half if direction == "top" else half
        if not math.isclose(float(observed[1]), expected_y, rel_tol=1e-12, abs_tol=1e-9):
            fail(f"Pet companion migration vector {vector['name']} maps the y coordinate incorrectly")
        expected_velocity = [float(value) for value in vector.get("velocity", [0.0, 0.0])]
        observed_velocity = [float(value) for value in vector.get("expectedVelocity", [])]
        if observed_velocity != expected_velocity:
            fail(f"Pet companion migration vector {vector['name']} does not preserve velocity")
        if direction == "top" and vector.get("expectedMode") != "fall":
            fail("Top-entry pet migration must enter FALL")
        if direction != "top" and vector.get("expectedMode") not in {"fling", "dragging"}:
            fail("Horizontal pet migration must preserve active mode")

    ray_vectors = payload.get("windowRayVectors", [])
    if {item.get("name") for item in ray_vectors} != {
        "gapped-diagonal-ray-rejects-near-miss-and-selects-first-hit",
    }:
        fail("Pet companion window motion-ray vectors differ")

    def ray_rect_entry_time(origin: list[float], velocity: list[float], rect: list[float], limit: float) -> float | None:
        near = 0.0
        far = limit
        for point, component, minimum, size in (
            (origin[0], velocity[0], rect[0], rect[2]),
            (origin[1], velocity[1], rect[1], rect[3]),
        ):
            maximum = minimum + size
            if size <= 0.0:
                return None
            if abs(component) <= 1e-12:
                if point < minimum or point > maximum:
                    return None
                continue
            first = (minimum - point) / component
            second = (maximum - point) / component
            axis_near, axis_far = sorted((first, second))
            near = max(near, axis_near)
            far = min(far, axis_far)
            if near > far + 1e-12:
                return None
        if far < -1e-12 or near > limit + 1e-12:
            return None
        return max(0.0, min(limit, near))

    for vector in ray_vectors:
        source = [float(value) for value in vector["sourceWindow"]["rect"]]
        origin = [float(value) for value in vector["rayOriginWorld"]]
        velocity = [float(value) for value in vector["velocity"]]
        limit = float(vector["lookaheadSeconds"])
        source_right = source[0] + source[2]
        if (
            len(source) != 4
            or len(origin) != 2
            or len(velocity) != 2
            or not all(math.isfinite(value) for value in (*source, *origin, *velocity, limit))
            or not math.isclose(origin[0], source_right, rel_tol=0.0, abs_tol=1e-9)
            or velocity[0] <= 0.0
            or velocity[1] == 0.0
            or limit <= 0.0
        ):
            fail("Pet companion window motion-ray vector must start diagonally at the source edge")
        intersections: list[tuple[float, int, str, list[float]]] = []
        rejected: list[str] = []
        candidates_by_id = {}
        for candidate in vector.get("candidates", []):
            candidate_id = candidate.get("id")
            rect = [float(value) for value in candidate["rect"]]
            if len(rect) != 4 or rect[0] <= source_right or candidate_id in candidates_by_id:
                fail("Pet companion window motion-ray candidates must be unique and separated by a positive gap")
            candidates_by_id[candidate_id] = rect
            actual_time = ray_rect_entry_time(origin, velocity, rect, limit)
            expected_time = candidate.get("expectedIntersectionTimeSeconds")
            if expected_time is None:
                if actual_time is not None:
                    fail(f"Pet companion motion ray unexpectedly hits {candidate_id}")
                rejected.append(candidate_id)
            else:
                expected_time = float(expected_time)
                if actual_time is None or not math.isclose(actual_time, expected_time, rel_tol=1e-12, abs_tol=1e-12):
                    fail(f"Pet companion motion ray has the wrong entry time for {candidate_id}")
                intersections.append((actual_time, int(candidate.get("order", 0)), candidate_id, rect))
        if not intersections:
            fail("Pet companion window motion-ray vector has no eligible hit")
        intersections.sort(key=lambda item: (item[0], item[1]))
        hit_time, _, hit_id, hit_rect = intersections[0]
        if rejected != vector.get("expectedRejected") or hit_id != vector.get("expectedHost"):
            fail("Pet companion window motion ray does not reject misses before selecting the earliest hit")
        if not math.isclose(hit_time, float(vector["expectedIntersectionTimeSeconds"]), rel_tol=1e-12, abs_tol=1e-12):
            fail("Pet companion window motion ray selects the wrong intersection time")
        hit_point = [origin[index] + velocity[index] * hit_time for index in (0, 1)]
        expected_point = [float(value) for value in vector["expectedIntersectionPoint"]]
        if any(not math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-9) for actual, expected in zip(hit_point, expected_point)):
            fail("Pet companion window motion ray selects the wrong intersection point")
        if vector.get("expectedEntryEdge") != "left" or not math.isclose(hit_point[0], hit_rect[0], rel_tol=0.0, abs_tol=1e-9):
            fail("Pet companion window motion ray enters through the wrong edge")
        miss_rect = candidates_by_id.get(vector["expectedRejected"][0])
        if miss_rect is None or not (miss_rect[1] <= origin[1] <= miss_rect[1] + miss_rect[3]) or miss_rect[0] >= hit_rect[0]:
            fail("Pet companion motion-ray miss vector does not distinguish projection scoring from ray intersection")

    expected_window_vectors = {
        "word-bubble-retains-main-pet": {
            "name": "word-bubble-retains-main-pet",
            "windowStack": ["main", "word-bubble"],
            "petHostStack": ["main"],
            "ownerMap": {"word-bubble": "main"},
            "triggerWindow": "main",
            "expectedPopupOwner": "main",
            "expectedActivePetHost": "main",
            "expectedVisiblePetWindows": ["main"],
            "expectedPetCount": 1,
            "boundsPolicy": "pet-host-window",
            "popupExitAllowed": True,
        },
        "learning-reminder-has-exactly-one-pet": {
            "name": "learning-reminder-has-exactly-one-pet",
            "windowStack": ["main", "learning-reminder"],
            "petHostStack": ["main", "learning-reminder"],
            "expectedActivePetHost": "learning-reminder",
            "expectedVisiblePetWindows": ["learning-reminder"],
            "expectedPetCount": 1,
            "boundsPolicy": "pet-host-window",
        },
        "learning-reminder-word-bubble-retains-reminder-pet": {
            "name": "learning-reminder-word-bubble-retains-reminder-pet",
            "windowStack": ["main", "learning-reminder", "word-bubble"],
            "petHostStack": ["main", "learning-reminder"],
            "ownerMap": {
                "learning-reminder": "main",
                "word-bubble": "learning-reminder",
            },
            "triggerWindow": "learning-reminder",
            "expectedPopupOwner": "learning-reminder",
            "expectedActivePetHost": "learning-reminder",
            "expectedVisiblePetWindows": ["learning-reminder"],
            "expectedPetCount": 1,
            "boundsPolicy": "pet-host-window",
            "popupExitAllowed": True,
        },
        "recursive-word-bubbles-retain-main-pet": {
            "name": "recursive-word-bubbles-retain-main-pet",
            "windowStack": ["main", "word-bubble-0", "word-bubble-1"],
            "petHostStack": ["main"],
            "ownerMap": {
                "word-bubble-0": "main",
                "word-bubble-1": "word-bubble-0",
            },
            "expectedActivePetHost": "main",
            "expectedVisiblePetWindows": ["main"],
            "expectedPetCount": 1,
            "boundsPolicy": "pet-host-window",
            "popupExitAllowed": True,
        },
        "destroyed-reminder-cleans-child-bubble-and-restores-main": {
            "name": "destroyed-reminder-cleans-child-bubble-and-restores-main",
            "windowStack": ["main", "learning-reminder", "word-bubble"],
            "petHostStack": ["main", "learning-reminder"],
            "ownerMap": {
                "learning-reminder": "main",
                "word-bubble": "learning-reminder",
            },
            "deactivatedWindow": "learning-reminder",
            "deactivationEvents": ["destroy"],
            "cascadeDestroyed": ["word-bubble"],
            "expectedWindowStack": ["main"],
            "expectedPetHostStack": ["main"],
            "expectedActivePetHost": "main",
            "expectedVisiblePetWindows": ["main"],
            "expectedPetCount": 1,
            "boundsPolicy": "pet-host-window",
        },
    }
    window_vectors = {item.get("name"): item for item in payload.get("windowScopeVectors", [])}
    if window_vectors != expected_window_vectors:
        fail("Pet companion active-window ownership vectors differ")
    for vector in window_vectors.values():
        stack = vector.get("windowStack", [])
        if not stack or stack[0] != "main" or len(stack) != len(set(stack)):
            fail(f"Pet companion window vector {vector['name']} has an invalid window stack")
        host_stack = vector.get("petHostStack", [])
        if (
            not host_stack
            or host_stack[0] != "main"
            or len(host_stack) != len(set(host_stack))
            or any(host not in stack for host in host_stack)
            or any("word-bubble" in host for host in host_stack)
        ):
            fail(f"Pet companion window vector {vector['name']} has an invalid pet-host stack")
        visible = vector.get("expectedVisiblePetWindows")
        active_host_stack = vector.get("expectedPetHostStack", host_stack)
        if (
            vector.get("expectedPetCount") != 1
            or visible != [vector.get("expectedActivePetHost")]
            or not active_host_stack
            or vector.get("expectedActivePetHost") != active_host_stack[-1]
            or vector.get("boundsPolicy") != "pet-host-window"
        ):
            fail(f"Pet companion window vector {vector['name']} violates single pet-host ownership")
        owner_map = vector.get("ownerMap")
        if owner_map is not None:
            expected_owner_map = {window: stack[index - 1] for index, window in enumerate(stack[1:], start=1)}
            if owner_map != expected_owner_map:
                fail(f"Pet companion window vector {vector['name']} has a non-recursive owner map")
            for window in stack[1:]:
                seen: set[str] = set()
                current = window
                while current != "main":
                    if current in seen or current not in owner_map:
                        fail(f"Pet companion window vector {vector['name']} has a cyclic or orphaned owner chain")
                    seen.add(current)
                    current = owner_map[current]
        trigger_window = vector.get("triggerWindow")
        if trigger_window is not None:
            if (
                trigger_window not in stack[:-1]
                or vector.get("expectedPopupOwner") != trigger_window
                or "word-bubble" not in vector["windowStack"][-1]
                or vector.get("expectedActivePetHost") != host_stack[-1]
            ):
                fail(f"Pet companion window vector {vector['name']} violates recursive popup ownership")
        if vector.get("popupExitAllowed") is not None:
            if (
                vector.get("popupExitAllowed") is not True
                or vector.get("boundsPolicy") != "pet-host-window"
                or any("word-bubble" in host for host in host_stack)
            ):
                fail(f"Pet companion window vector {vector['name']} traps the pet in a popup")
        deactivated_window = vector.get("deactivatedWindow")
        if deactivated_window is not None:
            cascade = vector.get("cascadeDestroyed", [])
            expected_stack = vector.get("expectedWindowStack")
            removed = {deactivated_window, *cascade}
            if (
                deactivated_window not in stack
                or vector.get("deactivationEvents") != ["destroy"]
                or expected_stack != [window for window in stack if window not in removed]
                or vector.get("expectedPetHostStack") != [host for host in host_stack if host not in removed]
                or vector.get("expectedActivePetHost") != vector.get("expectedPetHostStack", [])[-1]
            ):
                fail(f"Pet companion window vector {vector['name']} violates owner-destroy cleanup")
    parity = json.loads((CONTRACTS / "parity.json").read_text(encoding="utf-8"))
    if parity.get("petCompanionVersion") != "pet-companion-v1":
        fail("Parity manifest does not declare pet-companion-v1")
    pet = parity.get("petCompanion", {})
    if pet != {
        "name": "冰子",
        "tickMs": 16,
        "displaySize": 112,
        "idleTicks": 24,
        "curveAcceleration": 0.25,
        "curveAccelerationPolicy": "constant-independent-of-requested-step",
        "curveLandingVelocityProjection": "world-velocity-dot-local-unit-tangent",
        "curveVelocityUnits": "logical-units-per-tick",
        "curveCoordinateScalePolicy": "logical-velocity-physical-path-budget",
        "curveLandingSpeedLimit": 8.0,
        "curveDownhillTerminalSpeed": 4.0,
        "curveDownhillResponsePerTick": 0.0625,
        "curveDirectionEpsilon": 0.000001,
        "curveLandingRestDirection": "local-positive-y-downhill",
        "curveLandingInitialUphillMotion": True,
        "curveUphillEndpointPolicy": "stop-and-reverse-downhill",
        "targetKinds": ["control", "surface", "chart", "edge"],
        "navigationTransition": "drop-to-nearest",
        "supportSide": "upper",
        "screenEdges": ["left", "right", "bottom"],
        "acceleratedFall": True,
        "fallTimeStepSeconds": 0.016,
        "fallGravityLogicalUnitsPerSecondSquared": 2148.4375,
        "fallVelocityUnits": "logical-units-per-second",
        "fallIntegration": "closed-form-constant-acceleration",
        "maxFallSpeed": None,
        "noUpwardFall": True,
        "noBelowTargetPolicy": "fall-to-viewport-bottom-support",
        "fallAxis": "vertical-only",
        "fallTargetIntersection": "current-x-ray",
        "fallTargetRefresh": "every-tick-nearest-current-x-ray",
        "landingImpactVelocity": "continuous-contact",
        "syntheticBottomLanding": "same-impact-and-bounce-rules",
        "flingGravityLogicalUnitsPerSecondSquared": 2148.4375,
        "flingHorizontalRestitution": 0.72,
        "maxSubstepSeconds": 0.004,
        "maxSubstepsPerTick": 8,
        "highSpeedInterpolation": "linear-between-simulated-substeps",
        "flingChartContactDirection": "contact-equation-derivative-nonnegative",
        "hardLandingBounces": 2,
        "bounceDecay": 0.55,
        "horizontalFlip": True,
        "centerBiasedSelection": True,
        "windowScope": "application-owned-window",
        "singleActivePet": True,
        "activeWindowBounds": "pet-host-window",
        "wordBubblePetScope": "trigger-window-retained",
        "wordBubbleExit": "drag-and-autonomous",
        "wordBubbleEscapeClearance": "full-display-size",
        "learningReminderPetCount": 1,
        "nestedPopupOwner": "recursive-trigger-window",
        "activeWindowSelection": "focus-map-host-z-order",
        "windowDeactivationFallback": "next-mapped-host-z-order",
        "platformManagedUiExcluded": True,
        "windowMigration": {
            "enabled": True,
            "entryDirections": ["left", "right", "top"],
            "dragEntry": True,
            "boundaryPolicy": "portal-at-viewport-edge",
            "candidateSelection": "earliest-motion-intersection",
            "rayIntersection": "continuous-parametric-aabb",
            "rayMissPolicy": "reject",
            "overlapPolicy": "autonomous-reject-explicit-drag-allow",
            "positionMapping": "full-display-inner-edge",
            "stateTransfer": "preserve-velocity-and-grab-offset",
            "curveContactTransfer": "clear-source-local-target-and-velocity",
        },
        "dragPlacement": "preserve-grab-offset",
        "suspendedDragRelease": "fall",
        "releaseVelocitySampleWindowMs": 120,
        "minimumFlingSpeed": 90.0,
        "maxFlingSpeed": 1800.0,
        "velocityEstimator": "weighted-terminal-linear-regression",
        "flingMode": "fling",
        "flingCollision": "continuous-contact",
        "transientOnly": True,
    }:
        fail("Parity manifest does not declare transient Bingzi state")
    branding = parity.get("branding", {})
    if (
        branding.get("petImage") != payload.get("sourceAsset")
        or branding.get("petRuntimeImage") != payload.get("runtimeAsset")
        or branding.get("petRuntimeImageLeft") != payload.get("runtimeAssetLeft")
    ):
        fail("Parity and pet golden asset paths differ")
GROUP_ORDER = ["all", "cet4", "cet6", "zk", "gk", "custom"]
GROUP_RULES = [
    ("cet4", {"CET4"}, {"cet4"}),
    ("cet6", {"CET6"}, {"cet6"}),
    ("zk", {"ZK"}, {"zk"}),
    ("gk", {"GK"}, {"gk"}),
]


def verify_pet_vitals_contract() -> None:
    contract_path = CONTRACTS / "pet-vitals-v1.md"
    golden_path = CONTRACTS / "pet-vitals-golden-v1.json"
    if not contract_path.is_file() or "pet-vitals-v1" not in contract_path.read_text(encoding="utf-8"):
        fail("Pet vitals contract is missing or has the wrong version")
    if not golden_path.is_file():
        fail("Pet vitals golden file is missing")

    payload = json.loads(golden_path.read_text(encoding="utf-8"))
    if payload.get("contractVersion") != "pet-vitals-v1":
        fail("Unexpected pet vitals contract version")
    if payload.get("defaults") != {
        "satiety": 50.0,
        "foodReserve": 0.0,
        "mood": "calm",
    }:
        fail("Pet vitals defaults differ")
    food_jar = payload.get("foodJar", {})
    if food_jar != {
        "model": "value-object",
        "aggregateOwner": "pet-vitals",
        "persistedField": "foodReserve",
    }:
        fail("Food jar must be an explicit PetVitals value object")
    if payload.get("bounds") != {
        "satietyMinimum": 0.0,
        "satietyMaximum": 100.0,
        "foodReserveMinimum": 0.0,
        "foodReserveMaximum": 200.0,
    }:
        fail("Pet vitals bounds differ")
    hunger = payload.get("hunger", {})
    if hunger != {
        "hungryBelow": 30.0,
        "satedFromInclusive": 30.0,
        "satisfiedFromInclusive": 70.0,
        "reserveRefillTarget": 50.0,
        "reserveTransferRatio": 1.0,
    }:
        fail("Pet hunger thresholds differ")
    moods = payload.get("moods", [])
    if [(item.get("name"), item.get("label")) for item in moods] != [
        ("sad", "悲伤"),
        ("worried", "担忧"),
        ("happy", "开心"),
        ("excited", "兴奋"),
        ("bored", "无聊"),
        ("calm", "平静"),
    ]:
        fail("Pet mood values differ")

    overflow = payload.get("overflow", {})
    if (
        overflow.get("satietyToFoodReserveRatio") != 0.2
        or overflow.get("directFoodReserveRatio") != 1.0
        or overflow.get("order") != [
            "apply-satiety-and-convert-overflow",
            "apply-direct-food-reserve",
            "clamp-food-reserve",
            "auto-refill-if-hungry",
        ]
    ):
        fail("Pet vitals overflow order or ratios differ")

    tags = payload.get("temporaryReviewTags", {})
    forgot = "ToBeReviewed_Forgot"
    vague = "ToBeReviewed_Vague"
    if tags != {
        "forgot": forgot,
        "vague": vague,
        "cardinality": "zero-or-one",
        "malformedConflictPrecedence": [forgot, vague],
        "vocabularyTag": False,
        "persisted": True,
        "visible": False,
    }:
        fail("Temporary review tag semantics differ")

    expected_rewards = {
        ("study", None, "again"): (0.0, 0.0, forgot),
        ("study", None, "hard"): (0.0, 0.0, vague),
        ("study", None, "good"): (2.0, 0.0, None),
        ("study", None, "easy"): (3.0, 0.0, None),
        ("review", None, "again"): (0.0, 0.0, forgot),
        ("review", None, "hard"): (0.0, 0.0, vague),
        ("review", None, "good"): (0.2, 0.5, None),
        ("review", None, "easy"): (0.3, 0.8, None),
        ("review", vague, "again"): (0.0, 0.0, forgot),
        ("review", vague, "hard"): (0.0, 0.0, vague),
        ("review", vague, "good"): (1.0, 0.7, None),
        ("review", vague, "easy"): (1.2, 1.0, None),
        ("review", forgot, "again"): (0.0, 0.0, forgot),
        ("review", forgot, "hard"): (0.0, 0.0, vague),
        ("review", forgot, "good"): (1.5, 0.9, None),
        ("review", forgot, "easy"): (2.0, 1.4, None),
    }
    actual_rewards = {}
    for rule in payload.get("rewardRules", []):
        key = (rule.get("phase"), rule.get("priorTag"), rule.get("rating"))
        if key in actual_rewards:
            fail(f"Duplicate pet rating reward rule: {key}")
        actual_rewards[key] = (
            float(rule.get("satietyGain", -1.0)),
            float(rule.get("foodReserveGain", -1.0)),
            rule.get("nextTag"),
        )
    if actual_rewards != expected_rewards:
        fail("Pet rating reward matrix differs")

    def hunger_state(satiety: float) -> str:
        if satiety < float(hunger["hungryBelow"]):
            return "hungry"
        if satiety < float(hunger["satisfiedFromInclusive"]):
            return "sated"
        return "satisfied"

    hunger_vectors = payload.get("hungerStateVectors", [])
    expected_hunger_vectors = [
        (0.0, "hungry"),
        (29.999, "hungry"),
        (30.0, "sated"),
        (69.999, "sated"),
        (70.0, "satisfied"),
        (100.0, "satisfied"),
    ]
    if [
        (float(vector.get("satiety", -1.0)), vector.get("expected"))
        for vector in hunger_vectors
    ] != expected_hunger_vectors:
        fail("Pet hunger vectors are incomplete or reordered")
    for vector in hunger_vectors:
        if hunger_state(float(vector["satiety"])) != vector.get("expected"):
            fail(f"Pet hunger vector differs at {vector['satiety']}")

    bounds = payload["bounds"]
    vital_vectors = payload.get("vitalChangeVectors", [])
    expected_vital_vector_names = [
        "satiety-overflow-converts-at-twenty-percent",
        "direct-food-reserve-is-not-discounted",
        "combined-gains-respect-reserve-cap",
        "hungry-state-refills-to-fifty",
        "insufficient-reserve-is-fully-consumed",
        "threshold-does-not-trigger-refill",
    ]
    if [vector.get("name") for vector in vital_vectors] != expected_vital_vector_names:
        fail("Pet vital-change vectors are incomplete or reordered")
    for vector in vital_vectors:
        raw_satiety = float(vector["satiety"]) + float(vector["satietyGain"])
        overflow_amount = max(0.0, raw_satiety - float(bounds["satietyMaximum"]))
        satiety = min(float(bounds["satietyMaximum"]), max(float(bounds["satietyMinimum"]), raw_satiety))
        reserve = min(
            float(bounds["foodReserveMaximum"]),
            max(
                float(bounds["foodReserveMinimum"]),
                float(vector["foodReserve"])
                + float(vector["foodReserveGain"])
                + overflow_amount * float(overflow["satietyToFoodReserveRatio"]),
            ),
        )
        if satiety < float(hunger["hungryBelow"]):
            transfer = min(float(hunger["reserveRefillTarget"]) - satiety, reserve)
            satiety += transfer
            reserve -= transfer
        if not math.isclose(satiety, float(vector["expectedSatiety"]), abs_tol=1e-9):
            fail(f"Pet vital vector {vector['name']} differs at satiety")
        if not math.isclose(reserve, float(vector["expectedFoodReserve"]), abs_tol=1e-9):
            fail(f"Pet vital vector {vector['name']} differs at food reserve")

    effect = payload.get("rewardFlight", {})
    expected_effect = {
        "studyColor": "#F4C542",
        "reviewColor": "platform-primary-teal",
        "sourceAnchor": "pointer-down-screen-position",
        "targetTracking": "rendered-pet-center-every-frame",
        "frameMs": 16,
        "spiralDurationMs": 180,
        "spiralTurns": 1.0,
        "spiralRadiusStart": 4.0,
        "spiralRadiusEnd": 18.0,
        "homingInitialSpeed": 180.0,
        "homingAcceleration": 2400.0,
        "homingMaximumSpeed": 2800.0,
        "orbRadius": 6.0,
        "visual": {
            "orbRadius": 16.0,
            "orbGlowRadius": 34.0,
            "orbHighlightRadius": 4.0,
            "trailMinimumStrokeWidth": 5.0,
            "trailMaximumStrokeWidth": 12.0,
            "trailStrokeSpeedFactor": 0.0025,
            "trailGlowWidthMultiplier": 2.2,
            "burstParticleRadius": 4.0,
            "burstParticleGlowRadius": 10.0,
        },
        "trailLifetimeMs": 180,
        "trailMaximumPoints": 20,
        "trailLengthFormula": "clamp(18,96,speed*0.04)",
        "burstParticleCount": 18,
        "burstDurationMs": 350,
        "maximumLifetimeMs": 2500,
        "missingTargetTimeoutMs": 500,
        "minimumVerifiedConcurrentFlights": 32,
        "contactRadius": "pet-half-size-plus-orb-radius",
        "concurrency": "independent-no-replacement",
        "persisted": False,
    }
    if effect != expected_effect:
        fail("Pet reward-flight parameters differ")
    if payload.get("rewardFlightVectors") != {
        "spiralEndpoint": {
            "elapsedMs": 180,
            "relativeX": 18.0,
            "relativeY": 0.0,
        },
        "trailClip": {
            "speed": 1000.0,
            "inputX": [0.0, 25.0, 50.0, 75.0],
            "expectedStartX": 35.0,
            "expectedEndX": 75.0,
            "expectedLength": 40.0,
        },
    }:
        fail("Pet reward-flight trajectory vectors differ")

    contract_text = contract_path.read_text(encoding="utf-8")
    for marker in (
        "20%",
        "single-value enum",
        "not a vocabulary/catalog",
        "current rendered center",
        "`FoodJar` domain value object",
        "cross-repository",
        "single failed frame",
    ):
        if marker not in contract_text:
            fail(f"Pet vitals contract is missing {marker}")
    parity = json.loads((CONTRACTS / "parity.json").read_text(encoding="utf-8"))
    if parity.get("petVitalsVersion") != "pet-vitals-v1":
        fail("Parity manifest does not declare pet-vitals-v1")
    expected_manifest_vitals = {
        "satiety": {
            "minimum": float(bounds["satietyMinimum"]),
            "maximum": float(bounds["satietyMaximum"]),
            "default": float(payload["defaults"]["satiety"]),
        },
        "foodReserve": {
            "minimum": float(bounds["foodReserveMinimum"]),
            "maximum": float(bounds["foodReserveMaximum"]),
            "default": float(payload["defaults"]["foodReserve"]),
        },
        "foodJar": food_jar,
        "hunger": {
            "hungryBelow": float(hunger["hungryBelow"]),
            "satisfiedFromInclusive": float(hunger["satisfiedFromInclusive"]),
            "reserveRefillTarget": float(hunger["reserveRefillTarget"]),
        },
        "overflowToFoodReserveRatio": float(overflow["satietyToFoodReserveRatio"]),
        "moods": [item["name"] for item in moods],
        "defaultMood": payload["defaults"]["mood"],
        "temporaryReviewTags": [forgot, vague],
        "temporaryReviewTagCardinality": tags["cardinality"],
        "persisted": True,
        "visible": False,
        "rewardFlight": {
            "studyColor": effect["studyColor"],
            "reviewColor": effect["reviewColor"],
            "sourceAnchor": effect["sourceAnchor"],
            "targetTracking": effect["targetTracking"],
            "concurrency": effect["concurrency"],
            "visual": effect["visual"],
        },
    }
    if parity.get("petVitals") != expected_manifest_vitals:
        fail("Parity petVitals projection differs from the golden contract")
    capabilities = parity.get("capabilities", {})
    for capability in (
        "petVitalsAndRatingRewards",
        "ratingRewardFlightEffect",
        "petMotionContinuityDuringReflow",
        "petAnimationFrameResilience",
    ):
        if capabilities.get(capability) != "ready":
            fail(f"Parity capability {capability} is not ready")

    implementation_markers = {
        "windows/domain/pet_vitals.py": (
            "class FoodJar",
            "class PetVitals",
            "class ReviewRecoveryTag",
            "apply_rating_reward",
        ),
        "windows/application/services.py": (
            "apply_rating_reward",
            "save_learning_outcome",
            "save_review_outcome",
            "restore_review_savepoint",
        ),
        "windows/infrastructure/repository.py": (
            "save_review_outcome",
            "restore_review_savepoint",
            "review savepoint is stale",
        ),
        "windows/infrastructure/words_learnt_repository.py": (
            "save_learning_outcome",
            "petVitals",
        ),
        "windows/presentation/reward_effects.py": (
            "class RewardEffectsController",
            "clip_trail_to_length",
            "trail_length_for_speed",
            "A single failed frame",
        ),
        "windows/presentation/app.py": (
            "Skip the failed frame and keep ticking",
        ),
        "windows/tests/test_pet_vitals.py": ("FoodJar", "rewardRules"),
        "windows/tests/test_reward_effects.py": (
            "minimumVerifiedConcurrentFlights",
            "pointer_source_uses_press_coordinates",
        ),
        "android/domain/src/main/kotlin/com/lexitrack/learning/domain/PetVitals.kt": (
            "class FoodJar",
            "data class PetVitals",
            "reduceRatingReward",
        ),
        "android/application/src/main/kotlin/com/lexitrack/learning/application/LearningUseCases.kt": (
            "reduceRatingReward",
            "saveLearningOutcome",
            "rollbackReview",
        ),
        "android/infrastructure/src/main/kotlin/com/lexitrack/learning/infrastructure/AndroidReviewRepository.kt": (
            "NonCancellable",
            "ReviewSavepoint",
            "rollbackReview",
            "Review savepoint is stale",
        ),
        "android/infrastructure/src/main/kotlin/com/lexitrack/learning/infrastructure/AndroidLearntWordsRepository.kt": (
            "NonCancellable",
            "saveLearningOutcome",
            "petVitals",
        ),
        "android/infrastructure/src/test/kotlin/com/lexitrack/learning/infrastructure/AndroidReviewRepositoryTest.kt": (
            "cancellationAfterCommitStillPublishesReviewState",
            "cancellationAfterReviewCommitCannotSplitTheRatingOutcome",
        ),
        "android/infrastructure/src/test/kotlin/com/lexitrack/learning/infrastructure/AndroidLearntWordsRepositoryTest.kt": (
            "cancellationAfterCommitStillPublishesLearningOutcome",
        ),
        "android/presentation/src/main/kotlin/com/lexitrack/learning/presentation/RewardEffects.kt": (
            "class RewardEffectsEngine",
            "resolveRatingOrigin",
            "visibleTrail",
            "trailLengthForSpeed",
        ),
        "android/presentation/src/main/kotlin/com/lexitrack/learning/presentation/LexiTrackApp.kt": (
            "onRate(ReviewRating.AGAIN",
            "onRate(ReviewRating.HARD",
            "onRate(ReviewRating.GOOD",
            "onRate(ReviewRating.EASY",
            "resolveRatingOrigin",
            "Skip the failed frame and keep the loop alive",
        ),
        "android/domain/src/test/kotlin/com/lexitrack/learning/domain/PetVitalsGoldenContractTest.kt": (
            "FoodJar",
            "rewardRules",
        ),
        "android/presentation/src/test/kotlin/com/lexitrack/learning/presentation/RewardEffectsTest.kt": (
            "minimumVerifiedConcurrentFlights",
            "trailLengthForSpeed",
        ),
    }
    for relative_path, markers in implementation_markers.items():
        source_path = ROOT / relative_path
        if not source_path.is_file():
            fail(f"Pet vitals implementation is missing {relative_path}")
        source = source_path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in source:
                fail(f"Pet vitals implementation {relative_path} is missing {marker}")

    hidden_ui_markers = (
        "饱食度",
        "储食度",
        "饥饿状态",
        forgot,
        vague,
    )
    presentation_sources = [
        ROOT / "windows" / "presentation" / "app.py",
        ROOT / "android" / "presentation" / "src" / "main" / "kotlin" /
        "com" / "lexitrack" / "learning" / "presentation" / "LexiTrackApp.kt",
    ]
    for source_path in presentation_sources:
        source = source_path.read_text(encoding="utf-8")
        for marker in hidden_ui_markers:
            if marker in source:
                fail(f"Hidden pet state leaked into UI: {source_path.relative_to(ROOT)} has {marker}")


def normalize_group_membership(code: str) -> str:
    normalized = unicodedata.normalize("NFKC", code.strip()).upper()
    return "".join(ch for ch in normalized if ch not in " -_.")


def normalize_group_tag(tag: str) -> str:
    return unicodedata.normalize("NFKC", tag.strip()).casefold()


def classify_vocabulary_groups(memberships, tags) -> list[str]:
    levels = {normalize_group_membership(value) for value in memberships}
    normalized_tags = {normalize_group_tag(value) for value in tags}
    result = {"all"}
    for key, level_codes, tag_codes in GROUP_RULES:
        if (levels & level_codes) or (normalized_tags & tag_codes):
            result.add(key)
    if "CUSTOM" in levels:
        result.add("custom")
    return sorted(result)


def verify_vocabulary_groups_contract() -> None:
    contract_path = CONTRACTS / "vocabulary-groups-v1.md"
    golden_path = CONTRACTS / "vocabulary-groups-golden-v1.json"
    if not contract_path.is_file() or "vocabulary-groups-v1" not in contract_path.read_text(encoding="utf-8"):
        fail("Vocabulary groups contract is missing or has the wrong version")
    if not golden_path.is_file():
        fail("Vocabulary groups golden file is missing")
    payload = json.loads(golden_path.read_text(encoding="utf-8"))
    if payload.get("contractVersion") != "vocabulary-groups-v1":
        fail("Vocabulary groups golden version differs from the shared contract")

    order = list(payload.get("groupOrder", []))
    labels = payload.get("groupLabels", {})
    if not order or order[0] != "all":
        fail("Vocabulary groups must order the 'all' group first")
    if not all(code in labels for code in order):
        fail("Every canonical vocabulary group must have a display label")
    if labels.get("all") != "全部":
        fail("The 'all' group label must be 全部")

    for raw, expected in payload.get("normalize", {}).items():
        if normalize_group_membership(raw) != expected:
            fail(f"Vocabulary group membership normalization differs for {raw!r}")

    counts = dict.fromkeys(order, 0)
    for fixture in payload.get("fixtures", []):
        fid = str(fixture.get("id", ""))
        if not fid:
            fail("Vocabulary groups fixture has a blank id")
        expected_groups = sorted(str(value) for value in fixture.get("expectedGroups", []))
        actual = classify_vocabulary_groups(fixture.get("memberships", []), fixture.get("tags", []))
        if actual != expected_groups:
            fail(f"Vocabulary group classifier diverges for {fid}: {actual} != {expected_groups}")
        for key in actual:
            counts[key] += 1

    expected_counts = payload.get("expected", {}).get("groupCounts", {})
    if counts != expected_counts:
        fail(f"Vocabulary group counts differ from the golden vector: {counts} != {expected_counts}")
    if counts.get("all", 0) != len(payload.get("fixtures", [])):
        fail("Vocabulary groups 'all' count must equal the fixture count")

    parity = json.loads((CONTRACTS / "parity.json").read_text(encoding="utf-8"))
    if parity.get("vocabularyGroupsVersion") != "vocabulary-groups-v1":
        fail("Parity manifest does not declare vocabulary-groups-v1")
    if parity.get("capabilities", {}).get("vocabularyGroupBrowser") != "ready":
        fail("Parity manifest does not declare vocabularyGroupBrowser ready")
    if parity.get("capabilities", {}).get("dictationGroupSelection") != "ready":
        fail("Parity manifest does not declare dictationGroupSelection ready")
    if parity.get("capabilities", {}).get("dictationRandomGroupDrillDown") != "ready":
        fail("Parity manifest does not declare dictationRandomGroupDrillDown ready")
    if "Dictation word selection" not in contract_path.read_text(encoding="utf-8"):
        fail("Vocabulary groups contract must govern dictation word selection")
    contract_text = contract_path.read_text(encoding="utf-8")
    if "从该词书手选" not in contract_text:
        fail("Vocabulary groups contract must define random-group drill-down and manual handoff")

    windows_source = (ROOT / "windows" / "presentation" / "app.py").read_text(encoding="utf-8")
    android_source = (
        ROOT / "android" / "presentation" / "src" / "main" / "kotlin" /
        "com" / "lexitrack" / "learning" / "presentation" / "LexiTrackApp.kt"
    ).read_text(encoding="utf-8")
    for marker in ("open_dictation_group", "close_dictation_group", "从该词书手选"):
        if marker not in windows_source:
            fail(f"Windows dictation group drill-down is missing {marker}")
    for marker in ("openDictationGroup", "closeDictationGroup", "从该词书手选"):
        if marker not in android_source:
            fail(f"Android dictation group drill-down is missing {marker}")

    for marker in ("dictationRandomCandidateIds", "选取到这里", "结束范围选择"):
        if marker not in windows_source:
            fail(f"Windows dictation selection interaction is missing {marker}")
    for marker in ("dictationRandomCandidateIds", "选取到这里", "结束范围选择"):
        if marker not in android_source:
            fail(f"Android dictation selection interaction is missing {marker}")


def verify_dictation_presentation_contract() -> None:
    contract_path = CONTRACTS / "dictation-export-v1.md"
    contract_text = contract_path.read_text(encoding="utf-8")
    if "vocabulary-groups-v1" not in contract_text or "跨分组" not in contract_text:
        fail("Dictation contract must use the shared vocabulary-group scope")
    required_scope_markers = ("`all`", "`cet4`", "`cet6`", "`zk`", "`gk`", "`custom`")
    if any(marker not in contract_text for marker in required_scope_markers):
        fail("Dictation contract must name every canonical vocabulary group scope")
    if "额外规范化 membership group key" not in contract_text:
        fail("Dictation contract must allow additional normalized membership groups")
    if "筛选支持多选" in contract_text or "支持值为 `CET4`、`CET6`、`CUSTOM`" in contract_text:
        fail("Dictation contract still contains the legacy memberships multi-select scope")
    if "进入页面的加载动画" not in contract_text or "1000..2000 ms" not in contract_text:
        fail("Dictation contract must define the entry loading duration")
    if "圆环 spinner" not in contract_text or "打开书本" not in contract_text:
        fail("Dictation contract must require a visible book-turning animation")
    parity = json.loads((CONTRACTS / "parity.json").read_text(encoding="utf-8"))
    if parity.get("capabilities", {}).get("dictationBookLoadingAnimation") != "ready":
        fail("Parity manifest does not declare dictationBookLoadingAnimation ready")
    for capability in (
        "dictationRandomSubsetSelection",
        "dictationRangeSelection",
        "dictationDraftPersistence",
        "dictationDraftSyncPort",
    ):
        if parity.get("capabilities", {}).get(capability) != "ready":
            fail(f"Parity manifest does not declare {capability} ready")

    windows_source = (ROOT / "windows" / "presentation" / "widgets.py").read_text(encoding="utf-8")
    android_root = (
        ROOT / "android" / "presentation" / "src" / "main" / "kotlin" /
        "com" / "lexitrack" / "learning" / "presentation"
    )
    android_screen = (android_root / "LexiTrackApp.kt").read_text(encoding="utf-8")
    android_geometry = (android_root / "DictationPresentation.kt").read_text(encoding="utf-8")
    android_view_model = (android_root / "MainViewModel.kt").read_text(encoding="utf-8")
    for marker in ("book_turning_frame", "book_turning_progress", "BOOK_TURNING_TICK_MS"):
        if marker not in windows_source:
            fail(f"Windows book-turning loader is missing {marker}")
    for marker in ("dictationBookFrame", "DICTATION_BOOK_PAGE_TURN_MS"):
        if marker not in android_geometry:
            fail(f"Android book-turning geometry is missing {marker}")
    if "RepeatMode.Restart" not in android_screen or "RepeatMode.Reverse" in android_screen:
        fail("Android book-turning loader must restart each right-to-left page turn")
    if "stopDictationLoading()" not in android_view_model or "dictationLoadingJob?.cancel()" not in android_view_model:
        fail("Android must cancel the dictation loading job when leaving the page")
    windows_repository = (ROOT / "windows" / "infrastructure" / "repository.py").read_text(encoding="utf-8")
    android_repository = (
        ROOT / "android" / "infrastructure" / "src" / "main" / "kotlin" /
        "com" / "lexitrack" / "learning" / "infrastructure" /
        "AndroidDictationDraftRepository.kt"
    ).read_text(encoding="utf-8")
    for marker in ("save_last_synced_dictation_envelope", "add_dictation_conflict_backup"):
        if marker not in windows_repository:
            fail(f"Windows dictation sync persistence is missing {marker}")
    for marker in ("saveLastSyncedEnvelope", "addConflictBackup", "MAX_CONFLICT_BACKUPS = 3"):
        if marker not in android_repository:
            fail(f"Android dictation sync persistence is missing {marker}")


def verify_font_scale_popup_contract() -> None:
    """Verify cross-platform safety rules for font settings and popup geometry."""
    parity = json.loads((CONTRACTS / "parity.json").read_text(encoding="utf-8"))
    expected_font_scale = {
        "minimum": 0.9,
        "maximum": 1.4,
        "default": 1.0,
        "nonFinitePolicy": "fallback-to-default",
        "clampPolicy": "finite-input-clamp-to-range",
    }
    if parity.get("fontScale") != expected_font_scale:
        fail("Parity font-scale safety semantics differ")
    minimum = float(expected_font_scale["minimum"])
    maximum = float(expected_font_scale["maximum"])
    default = float(expected_font_scale["default"])
    if not (
        math.isfinite(minimum)
        and math.isfinite(maximum)
        and math.isfinite(default)
        and minimum <= default <= maximum
    ):
        fail("Parity font-scale bounds must be finite and contain the default")

    def clamp_font_scale(value: float) -> float:
        if not math.isfinite(value):
            return default
        return min(maximum, max(minimum, value))

    # Pure contract vectors cover both invalid persisted values and ordinary
    # finite values without importing either platform's settings code.
    vectors = (
        (float("nan"), default),
        (float("-inf"), default),
        (float("inf"), default),
        (minimum - 1.0, minimum),
        (minimum, minimum),
        (default, default),
        (maximum, maximum),
        (maximum + 1.0, maximum),
    )
    for raw, expected in vectors:
        observed = clamp_font_scale(raw)
        if not math.isclose(observed, expected, rel_tol=0.0, abs_tol=1e-12):
            fail(f"Font-scale contract vector differs for {raw!r}: {observed} != {expected}")

    expected_popup_geometry = {
        "initialPlacement": "measure-before-position-and-viewport-clamp",
    }
    if parity.get("popupGeometry") != expected_popup_geometry:
        fail("Parity popup initial-geometry semantics differ")


def verify_catalog() -> None:
    catalog_path = CONTENT / "catalog.json"
    manifest_path = CONTENT / "catalog-manifest.json"
    if not catalog_path.exists() or not manifest_path.exists():
        fail("Catalog and manifest must both exist")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    parity = json.loads((CONTRACTS / "parity.json").read_text(encoding="utf-8"))
    if manifest["contentVersion"] != parity["contentVersion"]:
        fail("Content version differs from parity manifest")
    if manifest["wordCount"] != len(catalog):
        fail("Manifest word count is stale")
    ids: set[str] = set()
    membership_counts = {"CET4": 0, "CET6": 0}
    allowed_memberships = {"CET4", "CET6", "ZK", "GK"}
    for item in catalog:
        entry_id = item.get("id", "")
        if not entry_id or entry_id in ids:
            fail(f"Duplicate or empty word id: {entry_id!r}")
        ids.add(entry_id)
        meaning = str(item.get("meaning", "")).strip()
        if not meaning or not re.search(r"[\u3400-\u9fff]", meaning):
            fail(f"Missing meaning: {entry_id}")
        memberships = item.get("memberships", [])
        if not memberships:
            fail(f"Missing membership: {entry_id}")
        for membership in memberships:
            if membership not in allowed_memberships:
                fail(f"Invalid membership {membership}: {entry_id}")
            if membership in membership_counts:
                membership_counts[membership] += 1
        examples = item.get("examples", [])
        if len(examples) < 3:
            fail(f"Fewer than three examples: {entry_id}")
        seen_examples: set[str] = set()
        for example in examples[:3]:
            english = str(example.get("en", "")).strip()
            chinese = str(example.get("zh", "")).strip()
            if not english or not chinese or not re.search(r"[\u3400-\u9fff]", chinese):
                fail(f"Incomplete bilingual example: {entry_id}")
            if TO_SIMPLIFIED.convert(chinese) != chinese:
                fail(f"Example translation is not Simplified Chinese: {entry_id}")
            if "\u200b" in chinese:
                fail(f"Example translation contains a zero-width space: {entry_id}")
            if english.casefold() in seen_examples:
                fail(f"Duplicate English example: {entry_id}")
            seen_examples.add(english.casefold())
    if membership_counts != manifest["membershipCounts"]:
        fail(f"Membership counts are stale: {membership_counts}")


def verify_branding() -> None:
    parity = json.loads((CONTRACTS / "parity.json").read_text(encoding="utf-8"))
    relative_path = parity.get("branding", {}).get("appImage")
    if not relative_path:
        fail("Shared app image is not declared")
    image_path = ROOT / relative_path
    if not image_path.is_file():
        fail(f"Shared app image is missing: {relative_path}")
    with image_path.open("rb") as image_file:
        signature = image_file.read(8)
    if signature != b"\x89PNG\r\n\x1a\n":
        fail(f"Shared app image is not a PNG: {relative_path}")
    pet_paths = parity.get("branding", {})
    expected_hashes = {
        "petImage": "ff8ce536c8ebf69f9f8990c94115842ac7c6fe3fac867265b031c396d18ec124",
        "petRuntimeImage": "eea2733972136eca55c20fa58d86add1e5378422028f72d2f1209d396c2a5fb7",
        "petRuntimeImageLeft": "e4b364dcd96c431df1962c3e9b12dc05f6787c1db52db330b43c07a7dea27294",
    }
    for key in ("petImage", "petRuntimeImage", "petRuntimeImageLeft"):
        pet_relative = pet_paths.get(key)
        if not pet_relative:
            fail(f"Shared {key} is not declared")
        pet_path = ROOT / pet_relative
        if not pet_path.is_file():
            fail(f"Shared pet image is missing: {pet_relative}")
        with pet_path.open("rb") as pet_file:
            pet_signature = pet_file.read(8)
        if pet_signature != b"\x89PNG\r\n\x1a\n":
            fail(f"Shared pet image is not a PNG: {pet_relative}")
        observed_hash = hashlib.sha256(pet_path.read_bytes()).hexdigest()
        if observed_hash != expected_hashes[key]:
            fail(f"Shared pet image hash differs: {pet_relative}")
    source_path = ROOT / pet_paths["petImage"]
    runtime_path = ROOT / pet_paths["petRuntimeImage"]
    runtime_left_path = ROOT / pet_paths["petRuntimeImageLeft"]
    with TemporaryDirectory(prefix="lexitrack-pet-") as temp_dir:
        generated_path = Path(temp_dir) / "bingzi.png"
        generated_left_path = Path(temp_dir) / "bingzi-left.png"
        prepare_pet_asset(source_path, generated_path, generated_left_path)
        if generated_path.read_bytes() != runtime_path.read_bytes():
            fail("Shared pet runtime image is not reproducible from the canonical source")
        if generated_left_path.read_bytes() != runtime_left_path.read_bytes():
            fail("Shared mirrored pet image is not reproducible from the canonical source")


def verify_pet_appearance_contract() -> None:
    contract_path = CONTRACTS / "pet-appearance-v1.md"
    golden_path = CONTRACTS / "pet-appearance-golden-v1.json"
    if not contract_path.is_file() or "pet-appearance-v1" not in contract_path.read_text(encoding="utf-8"):
        fail("Pet appearance contract is missing or has the wrong version")
    if not golden_path.is_file():
        fail("Pet appearance golden file is missing")

    payload = json.loads(golden_path.read_text(encoding="utf-8"))
    required_states = ["pain.png", "scared.png", "sleep.png", "hungry.png"]
    expected_thresholds = {
        "largeLandingSpeed": 437.5,
        "airborneSeconds": 3.0,
        "stationarySeconds": 30.0,
        "doubleTapWindowMs": 300,
        "hungrySatiety": 0.0,
    }
    expected_priority = ["pain", "scared", "hungry", "sleep", "happy", "normal"]
    if payload.get("contractVersion") != "pet-appearance-v1":
        fail("Unexpected pet appearance contract version")
    if payload.get("sourceDirectory") != "shared/assets/branding/pet_states":
        fail("Pet appearance source directory differs")
    if payload.get("runtimeDirectory") != "shared/assets/pets/states":
        fail("Pet appearance runtime directory differs")
    if payload.get("requiredStateAssets") != required_states:
        fail("Pet appearance required state assets differ")
    if payload.get("happyAssetPattern") != r"^happy([1-9][0-9]*)\.png$":
        fail("Pet appearance happy filename pattern differs")
    if payload.get("thresholds") != expected_thresholds:
        fail("Pet appearance thresholds differ")
    if payload.get("priority") != expected_priority:
        fail("Pet appearance priority differs")
    priority_decision = payload.get("priorityDecision")
    priority_confirmed = payload.get("priorityConfirmed")
    if priority_decision not in {"recommended-pain-before-scared", "confirmed-pain-before-scared"}:
        fail("Pet appearance priority decision is missing")
    if not isinstance(priority_confirmed, bool):
        fail("Pet appearance priority confirmation must be boolean")
    if priority_confirmed != (priority_decision == "confirmed-pain-before-scared"):
        fail("Pet appearance priority confirmation does not match the decision marker")
    if payload.get("missingAssetPolicy") != "skip-missing-choice-and-fallback-to-normal":
        fail("Pet appearance missing-asset policy differs")
    if payload.get("featureEnabledWhen") != "all-required-state-assets-and-at-least-one-happy-asset-exist-and-priority-is-confirmed":
        fail("Pet appearance enablement rule differs")

    source_path = ROOT / payload["sourceDirectory"]
    runtime_path = ROOT / payload["runtimeDirectory"]
    if not source_path.is_dir() or not runtime_path.is_dir():
        fail("Pet appearance source and runtime directories must both exist")

    try:
        discovered = pet_appearance_assets.discover(source_path)
    except Exception as exc:
        fail(f"Pet appearance source assets are invalid: {exc}")
    manifest_path = runtime_path / "manifest.json"
    if not manifest_path.is_file():
        fail("Pet appearance runtime manifest is missing")
    generated = json.loads(manifest_path.read_text(encoding="utf-8"))
    generated_projection = {
        "contractVersion": discovered["contractVersion"],
        "stateAssets": discovered["stateAssets"],
        "happyAssets": discovered["happyAssets"],
        "enabled": discovered["enabled"],
        "disabledReason": discovered["disabledReason"],
        "sourceDirectory": "shared/assets/branding/pet_states",
        "runtimeDirectory": "shared/assets/pets/states",
    }
    if generated != generated_projection:
        fail("Generated pet appearance manifest is stale or has unexpected fields")

    def runtime_asset_path(relative_name: str) -> Path:
        return runtime_path / relative_name

    expected_runtime_pngs: set[str] = set()
    for filename in pet_appearance_assets.STATE_FILES.values():
        source_file = source_path / filename
        runtime_file = runtime_asset_path(filename)
        if source_file.is_file():
            expected_runtime_pngs.add(filename)
            if not runtime_file.is_file():
                fail(f"Generated runtime asset is missing: {filename}")
            if source_file.read_bytes() != runtime_file.read_bytes():
                fail(f"Generated runtime asset differs from source: {filename}")
            if runtime_file.read_bytes()[:8] != pet_appearance_assets.PNG_SIGNATURE:
                fail(f"Generated runtime asset is not a PNG: {filename}")
        elif runtime_file.is_file():
            fail(f"Runtime asset exists without a source asset: {filename}")

    happy_source_path = source_path / "happy"
    happy_runtime_path = runtime_path / "happy"
    for filename in discovered["happyAssets"]:
        expected_runtime_pngs.add(f"happy/{filename}")
        source_file = happy_source_path / filename
        runtime_file = happy_runtime_path / filename
        if not runtime_file.is_file() or source_file.read_bytes() != runtime_file.read_bytes():
            fail(f"Generated happy runtime asset differs or is missing: {filename}")
        if runtime_file.read_bytes()[:8] != pet_appearance_assets.PNG_SIGNATURE:
            fail(f"Generated happy runtime asset is not a PNG: {filename}")

    observed_runtime_pngs = {
        path.relative_to(runtime_path).as_posix()
        for path in runtime_path.rglob("*.png")
        if path.is_file()
    }
    if observed_runtime_pngs != expected_runtime_pngs:
        fail("Runtime pet appearance PNG set differs from the generated manifest")

    availability = payload.get("currentAvailability")
    expected_availability = {
        "enabled": discovered["enabled"],
        "stateAssets": discovered["stateAssets"],
        "happyAssets": discovered["happyAssets"],
        "disabledReason": discovered["disabledReason"],
    }
    if availability != expected_availability:
        fail("Pet appearance golden current availability differs from generated assets")

    asset_set = payload.get("assetSet", {})
    if asset_set.get("stateAssets") != {
        "pain": "pain.png",
        "scared": "scared.png",
        "sleep": "sleep.png",
        "hungry": "hungry.png",
    } or asset_set.get("happyAssets") != ["happy1.png", "happy2.png"]:
        fail("Pet appearance golden asset set differs")

    def at_least(value: float, threshold: float) -> bool:
        return math.isfinite(value) and value >= threshold

    def expected_decision(context: dict) -> tuple[str, str | None, str]:
        if at_least(float(context.get("landingImpactSpeed", 0.0)), expected_thresholds["largeLandingSpeed"]):
            return "pain", "pain.png", "large-landing"
        if at_least(float(context.get("airborneSeconds", 0.0)), expected_thresholds["airborneSeconds"]):
            return "scared", "scared.png", "airborne-too-long"
        satiety = context.get("satiety")
        if satiety is not None and math.isfinite(float(satiety)) and float(satiety) <= expected_thresholds["hungrySatiety"]:
            return "hungry", "hungry.png", "satiety-zero"
        if (
            not bool(context.get("moving", False))
            and at_least(float(context.get("stationarySeconds", 0.0)), expected_thresholds["stationarySeconds"])
        ):
            return "sleep", "sleep.png", "stationary-too-long"
        if not bool(context.get("moving", False)) and bool(context.get("rapidDoubleTap", False)):
            happy_index = int(context.get("happyAssetIndex", 0)) % 2
            return "happy", ["happy1.png", "happy2.png"][happy_index], "stationary-double-tap"
        return "normal", None, "normal"

    vectors = payload.get("vectors", [])
    if not vectors:
        fail("Pet appearance golden vectors are missing")
    for vector in vectors:
        expected = (
            ("normal", None, "normal")
            if vector.get("assetSet") == "empty"
            else expected_decision(vector.get("context", {}))
        )
        observed = vector.get("expected", {})
        if (observed.get("appearance"), observed.get("asset"), observed.get("reason")) != expected:
            fail(f"Pet appearance golden vector differs: {vector.get('name')}")

    contract_text = contract_path.read_text(encoding="utf-8")
    for marker in (
        "`shared/assets/branding/pet_states/`",
        "`shared/assets/pets/states/`",
        "dragging",
        "airborneSeconds >= 3.0",
        "stationarySeconds >= 30.0",
        "listdir",
        "pain > scared > hungry > sleep > happy > normal",
        "priorityConfirmed",
        "disabled",
    ):
        if marker not in contract_text:
            fail(f"Pet appearance contract is missing {marker}")

    parity = json.loads((CONTRACTS / "parity.json").read_text(encoding="utf-8"))
    expected_manifest = {
        "sourceDirectory": payload["sourceDirectory"],
        "runtimeDirectory": payload["runtimeDirectory"],
        "requiredStateAssets": required_states,
        "happyAssetPattern": payload["happyAssetPattern"],
        "thresholds": expected_thresholds,
        "priority": expected_priority,
        "priorityDecision": payload["priorityDecision"],
        "missingAssetPolicy": payload["missingAssetPolicy"],
        "featureEnabledWhen": payload["featureEnabledWhen"],
        "enabled": discovered["enabled"] and priority_confirmed,
        "disabledReason": discovered["disabledReason"],
        "priorityConfirmed": priority_confirmed,
    }
    if parity.get("petAppearanceVersion") != "pet-appearance-v1":
        fail("Parity manifest does not declare pet-appearance-v1")
    if parity.get("petAppearance") != expected_manifest:
        fail("Parity petAppearance projection differs from the golden contract or asset manifest")
    expected_capability = "ready" if discovered["enabled"] and priority_confirmed else "disabled"
    if parity.get("capabilities", {}).get("petAppearanceStates") != expected_capability:
        fail("Pet appearance capability does not match asset availability")

    implementation_markers = {
        "tools/prepare_pet_appearance_assets.py": (
            "def discover",
            "def prepare",
            "_validate_png",
            "shared/assets/branding/pet_states",
            "shared/assets/pets/states",
        ),
        "windows/domain/pet_appearance.py": (
            "PET_APPEARANCE_VERSION",
            "class PetAppearance",
            "class PetAppearanceAssets",
            "class PetAppearanceContext",
            "def select_pet_appearance",
        ),
        "windows/tests/test_pet_appearance.py": (
            "pet-appearance-golden-v1.json",
            "select_pet_appearance",
        ),
        "android/domain/src/main/kotlin/com/lexitrack/learning/domain/PetAppearance.kt": (
            "PET_APPEARANCE_VERSION",
            "enum class PetAppearance",
            "data class PetAppearanceAssets",
            "data class PetAppearanceContext",
            "fun selectPetAppearance",
        ),
        "android/domain/src/test/kotlin/com/lexitrack/learning/domain/PetAppearanceTest.kt": (
            "pet.appearance.golden.path",
            "selectPetAppearance",
        ),
        "android/presentation/build.gradle.kts": (
            "shared/assets/pets/states",
            "happy/*.png",
        ),
        "windows/build.ps1": (
            "shared\\assets\\pets",
            "--add-data",
        ),
    }
    for relative_path, markers in implementation_markers.items():
        source_path = ROOT / relative_path
        if not source_path.is_file():
            fail(f"Pet appearance implementation is missing {relative_path}")
        source = source_path.read_text(encoding="utf-8")
        for marker in markers:
            if marker not in source:
                fail(f"Pet appearance implementation {relative_path} is missing {marker}")

    windows_domain_path = ROOT / "windows" / "domain" / "pet_appearance.py"
    windows_domain_tree = ast.parse(windows_domain_path.read_text(encoding="utf-8"))
    forbidden_windows_imports = {"tkinter", "pathlib", "os", "io"}
    for node in ast.walk(windows_domain_tree):
        if isinstance(node, ast.Import):
            imported_modules = {alias.name.split(".", 1)[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported_modules = {(node.module or "").split(".", 1)[0]}
        else:
            continue
        if forbidden_windows_imports & imported_modules:
            fail("Windows pet appearance domain imports a platform or filesystem module")

    android_domain_source = (
        ROOT / "android" / "domain" / "src" / "main" / "kotlin" /
        "com" / "lexitrack" / "learning" / "domain" / "PetAppearance.kt"
    ).read_text(encoding="utf-8")
    if re.search(r"(?m)^import\s+(?:android|androidx|java\.io|java\.nio|kotlin\.io)\.", android_domain_source):
        fail("Android pet appearance domain imports a platform or filesystem module")
    if "listdir" in windows_domain_path.read_text(encoding="utf-8") or "listFiles" in android_domain_source:
        fail("Pet appearance domain must not discover files")

    presentation_sources = (
        ROOT / "windows" / "presentation",
        ROOT / "android" / "presentation" / "src" / "main",
    )
    source_directory_marker = "shared/assets/branding/pet_states"
    for presentation_root in presentation_sources:
        for source_path in presentation_root.rglob("*.py"):
            if source_directory_marker in source_path.read_text(encoding="utf-8"):
                fail(f"Presentation directly references canonical pet appearance sources: {source_path.relative_to(ROOT)}")
        for source_path in presentation_root.rglob("*.kt"):
            if source_directory_marker in source_path.read_text(encoding="utf-8"):
                fail(f"Presentation directly references canonical pet appearance sources: {source_path.relative_to(ROOT)}")

    if discovered["enabled"] is False:
        for relative_path in (
            "windows/domain/pet_appearance.py",
            "android/domain/src/main/kotlin/com/lexitrack/learning/domain/PetAppearance.kt",
        ):
            source = (ROOT / relative_path).read_text(encoding="utf-8")
            if "normal" not in source:
                fail(f"Disabled pet appearance implementation lacks normal fallback: {relative_path}")


def verify_platform_markers() -> None:
    parity = json.loads((CONTRACTS / "parity.json").read_text(encoding="utf-8"))
    for platform in parity["platforms"]:
        marker_path = ROOT / platform / "platform-contract.json"
        if not marker_path.exists():
            fail(f"Missing platform marker: {marker_path.relative_to(ROOT)}")
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        for key in (
            "releaseVersion",
            "schemaVersion",
            "algorithmVersion",
            "wordBubbleVersion",
            "petCompanionVersion",
            "petVitalsVersion",
            "petAppearanceVersion",
            "vocabularyGroupsVersion",
            "contentVersion",
        ):
            if marker.get(key) != parity.get(key):
                fail(f"{platform} {key} differs from shared parity manifest")
        for key in (
            "branding",
            "petCompanion",
            "petVitals",
            "petAppearance",
            "fontScale",
            "popupGeometry",
            "learningReminder",
            "studyOrder",
            "vocabularyFilters",
        ):
            if marker.get(key) != parity.get(key):
                fail(f"{platform} {key} differs from shared parity manifest")
        if marker.get("capabilities") != parity.get("capabilities"):
            fail(f"{platform} capabilities differ from shared parity manifest")


def main() -> int:
    verify_scheduler()
    verify_weighted_review()
    verify_dictation_contract()
    verify_dictation_presentation_contract()
    verify_word_bubble_contract()
    verify_pet_contract()
    verify_pet_appearance_contract()
    verify_pet_vitals_contract()
    verify_vocabulary_groups_contract()
    verify_font_scale_popup_contract()
    verify_catalog()
    verify_branding()
    verify_platform_markers()
    print("Synchronization contract verified for Windows, Android and shared resources.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"sync verification failed: {exc}", file=sys.stderr)
        raise

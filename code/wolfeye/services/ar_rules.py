"""AR transitions ported from WolfEye master SettingsView.cpp.
Reference: majidnow/wolfeye@7e58f4af439c6fa9c9db51e4558936264401732a.
The disabled flags retain the company's button-state semantics.
"""
from __future__ import annotations

D, A, R, L = range(4)

def _next_mode(element: int, stage: int, mode: int) -> int:
    if element == 1 and stage == 0:
        return {R: L, L: D, D: A}.get(mode, R)
    if element in (1, 3) and stage in (1, 2):
        return L if mode == R else R
    if element == 2:
        return D if mode == R else R
    return {R: L, L: D}.get(mode, R)

def cycle_ar_stage(modes: list[int], disabled: list[bool], row: int, stage: int, sef: bool) -> tuple[list[int], list[bool]]:
    count = 4 if sef else 12
    if len(modes) != count or len(disabled) != count or not 0 <= row < (1 if sef else 3) or not 0 <= stage < 4 or any(mode not in range(4) for mode in modes):
        raise ValueError("Invalid AR stage pack or transition")
    modes, disabled = list(modes), list(disabled)
    if sef:
        _sef_change(modes, disabled, stage)
    else:
        _change(modes, disabled, row, stage)
    return modes, disabled

def _sef_change(modes: list[int], disabled: list[bool], stage_index: int) -> None:
    n = _next_mode(1, stage_index, modes[stage_index])
    modes[stage_index] = n
    if stage_index == 1:
        if n == L:
            modes[1] = L
            modes[2] = L
            disabled[1] = True
            disabled[2] = True
        elif n == D:
            modes[1] = D
            modes[2] = D
            modes[3] = D
            disabled[1] = True
            disabled[2] = True
        elif n == R:
            modes[1] = R
            modes[2] = R
            modes[3] = L
            disabled[1] = False
            disabled[2] = False
        else:
            modes[1] = A
            modes[2] = A
            modes[3] = A
    elif stage_index == 2:
        if n == R:
            disabled[2] = False
        elif n == L:
            modes[2] = L
            disabled[2] = True

def _change(modes: list[int], disabled: list[bool], row: int, stage_index: int) -> None:
    disabled[3] = disabled[11] = True
    n = _next_mode(row + 1, stage_index, modes[row * 4 + stage_index])
    modes[row * 4 + stage_index] = n
    stage_index += 1
    if row == 0:
        if stage_index == 1:
            if n == L:
                modes[1] = L
                modes[2] = L
                disabled[1] = True
                disabled[2] = True
                modes[4] = D
                modes[5] = D
                modes[6] = D
                disabled[4] = True
                disabled[5] = True
                disabled[6] = True
                disabled[7] = True
                modes[8] = L
                modes[9] = L
                modes[10] = L
                disabled[9] = True
                disabled[10] = True
            elif n == D:
                modes[1] = D
                modes[2] = D
                modes[3] = D
                disabled[1] = True
                disabled[2] = True
                modes[4] = D
                modes[5] = D
                modes[6] = D
                modes[7] = D
                disabled[4] = True
                disabled[5] = True
                disabled[6] = True
                disabled[7] = True
                modes[8] = D
                modes[9] = D
                modes[10] = D
                modes[11] = D
                disabled[8] = True
                disabled[9] = True
                disabled[10] = True
            elif n == R:
                modes[1] = R
                modes[2] = R
                modes[3] = L
                disabled[1] = False
                disabled[2] = False
                disabled[4] = False
                modes[4] = R
                modes[5] = R
                modes[6] = R
                disabled[5] = False
                disabled[6] = False
                modes[8] = R
                modes[9] = R
                modes[10] = R
                modes[11] = L
                disabled[8] = False
                disabled[9] = False
                disabled[10] = False
            else:
                modes[1] = A
                modes[2] = A
                modes[3] = A
        elif stage_index == 2:
            if n == R:
                disabled[2] = False
                if modes[4] == D and modes[5] == D:
                    disabled[5] = False
                elif modes[4] == D:
                    modes[5] = R
                else:
                    disabled[4] = False
                    disabled[5] = False
                    disabled[6] = False
                if modes[8] == R:
                    disabled[9] = False
            elif n == L:
                modes[2] = L
                disabled[2] = True
                if modes[4] == D and modes[5] == D:
                    modes[7] = D
                    modes[6] = D
                    disabled[6] = True
                    disabled[7] = True
                elif modes[4] == R:
                    modes[5] = D
                    modes[6] = D
                    disabled[4] = True
                    disabled[6] = True
                    disabled[7] = True
                elif modes[4] == D:
                    modes[5] = L
                    modes[6] = L
                    modes[7] = L
                    disabled[5] = True
                    disabled[6] = True
                    disabled[7] = True
                else:
                    modes[6] = D
                    disabled[6] = True
                modes[9] = L
                modes[10] = L
                modes[11] = L
                disabled[9] = True
                disabled[10] = True
                if modes[8] == R:
                    modes[9] = L
                    modes[10] = L
                    disabled[9] = True
                    disabled[10] = True
        elif stage_index == 3:
            if n == L:
                disabled[7] = True
                if modes[5] == D and modes[6] == R:
                    modes[6] = L
                elif modes[4] == D and modes[5] == D:
                    if modes[6] == R:
                        modes[6] = L
                elif modes[4] == D and modes[5] == R:
                    modes[6] = L
                else:
                    modes[6] = D
                    disabled[6] = True
                modes[10] = L
                disabled[10] = True
            elif n == R:
                if modes[5] == D and modes[6] == L:
                    modes[6] = R
                elif modes[6] == D:
                    disabled[6] = False
                    disabled[7] = False
                elif modes[4] == R and modes[5] == R:
                    modes[6] = D
                    modes[7] = D
                    disabled[6] = False
                    disabled[7] = False
                elif modes[5] == R:
                    if modes[4] == D:
                        modes[6] = R
                    else:
                        modes[6] = L
                elif modes[4] == D and modes[5] == D:
                    if modes[6] == L:
                        modes[6] = R
                elif modes[5] == D:
                    if modes[6] == L:
                        modes[6] = R
                if modes[9] == R:
                    disabled[10] = False
    elif row == 1:
        if stage_index == 1:
            if n == R:
                if modes[1] == L and modes[5] == D:
                    modes[4] = R
                    disabled[4] = True
                elif modes[1] == L and modes[5] == L:
                    modes[4] = R
                    disabled[4] = True
                    modes[5] = D
                    disabled[5] = False
                    modes[6] = D
                    modes[7] = D
                elif modes[1] == R:
                    modes[5] = R
                    disabled[5] = False
                    if modes[2] == R:
                        modes[6] = R
                        disabled[6] = False
                    elif modes[2] == L:
                        modes[6] = D
                        modes[7] = D
                        disabled[6] = True
                modes[7] = D
                if modes[2] == R:
                    disabled[7] = True
            elif n == D:
                modes[5] = D
                disabled[5] = False
                if (modes[6] != R or modes[6] != L) and modes[5] != D:
                    modes[6] = D
                    disabled[6] = False
                    modes[7] = D
                    disabled[7] = modes[2] == L
        elif stage_index == 2:
            if n == R:
                disabled[5] = True
                if modes[1] == L and modes[4] == D:
                    modes[5] = L
                    modes[6] = L
                    modes[7] = L
                    disabled[5] = True
                    disabled[6] = True
                    disabled[7] = True
                elif modes[1] == L and modes[4] == R:
                    modes[4] = D
                    disabled[4] = False
                    modes[5] = D
                    disabled[5] = False
                elif modes[2] == L:
                    modes[6] = L
                    modes[7] = L
                    disabled[6] = True
                    disabled[7] = True
                elif modes[2] == R and modes[4] == D:
                    modes[6] = R
                    modes[7] = L
                    disabled[6] = True
                    disabled[7] = True
            elif n == D:
                if modes[4] == R and modes[1] == L:
                    modes[4] = D
                    modes[5] = D
                    modes[6] = D
                    modes[7] = D
                    disabled[4] = False
                    disabled[5] = False
                else:
                    modes[6] = D
                    modes[7] = D
                    disabled[7] = modes[2] == L
                    disabled[6] = False
        elif stage_index == 3:
            if n == R:
                if modes[2] == L and modes[5] == D:
                    if modes[4] == R:
                        disabled[5] = True
                    modes[6] = L
                    disabled[6] = True
                    modes[7] = L
                    disabled[7] = True
                elif modes[4] == R and modes[5] == R:
                    modes[7] = D
                    disabled[7] = True
                elif modes[4] == R and modes[5] == D:
                    disabled[5] = True
                    disabled[6] = True
                    modes[7] = L
                    disabled[7] = True
                elif modes[4] == D and modes[5] == D:
                    disabled[6] = True
                    modes[7] = L
                    disabled[7] = True
                elif modes[2] == L:
                    modes[6] = L
                    disabled[6] = True
                    modes[7] = L
                elif modes[5] == D:
                    disabled[6] = True
                    modes[7] = L
                    disabled[7] = True
                else:
                    modes[7] = D
                    disabled[7] = True
            elif n == D:
                if modes[4] == R and modes[5] == R:
                    modes[7] = D
                    disabled[7] = False
        else:
            modes[7] = L
            disabled[7] = True
            if modes[4] == R and modes[5] == D and modes[6] == D:
                disabled[5] = True
    elif row == 2:
        if stage_index == 1:
            if n == L:
                modes[9] = L
                modes[10] = L
                modes[11] = L
                disabled[9] = True
                disabled[10] = True
            elif n == D:
                modes[9] = D
                modes[10] = D
                modes[11] = D
                disabled[9] = True
                disabled[10] = True
            elif n == R:
                modes[8] = modes[0]
                modes[9] = modes[1]
                modes[10] = modes[2]
                modes[11] = modes[3]
                disabled[9] = modes[9] != R
                disabled[10] = modes[10] != R
        elif stage_index == 2:
            if n == L:
                modes[10] = L
                modes[11] = L
                disabled[10] = True
            elif n == R:
                disabled[10] = False

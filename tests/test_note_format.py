from lecture_notes.common import math_markdown


def test_latex_delimiters_are_renderable_without_changing_formula_or_code():
    source=r'行内 \(x_i^2\)，块公式 \[\begin{pmatrix}a\\b\end{pmatrix}\]。'+'\n'+r'`\(code\)`'+'\n```tex\n'+r'\[code\]'+'\n```'
    result=math_markdown(source)
    assert '$x_i^2$' in result
    assert '$$\n'+r'\begin{pmatrix}a\\b\end{pmatrix}'+'\n$$' in result
    assert r'`\(code\)`' in result and r'\[code\]' in result
    assert math_markdown(result)==result

-- Pandoc Lua Filter for EngDoc EMD Directives

function RawInline(el)
  -- Transform raw HTML <br> or <br/> into native Pandoc LineBreak
  if el.format == 'html' and el.text:match('^<[bB][rR]%s*/?>$') then
    return pandoc.LineBreak()
  end
  return el
end

function Div(el)
  -- Intercept Pagebreak Divs
  if el.classes:includes('pagebreak') then
    return pandoc.RawBlock('openxml', '<w:p><w:r><w:br w:type="page"/></w:r></w:p>')
  end

  -- Intercept Section Breaks
  if el.classes:includes('section') then
    local orient = el.attributes['orientation'] or 'portrait'
    local cols = el.attributes['columns'] or '1'
    -- Emits raw openxml comment/marker for Stage 03 layout processing
    return pandoc.RawBlock('openxml', string.format('<!-- EngDoc Section orient=%s cols=%s -->', orient, cols))
  end

  return el
end


"""Unit tests for md_to_chatwork() — Markdown to Chatwork format conversion."""

from __future__ import annotations

from core.tools.chatwork import md_to_chatwork


class TestMdToChatworkEmpty:
    def test_empty_string(self):
        assert md_to_chatwork("") == ""

    def test_none_like(self):
        assert md_to_chatwork("") == ""

    def test_plain_text(self):
        assert md_to_chatwork("Hello World") == "Hello World"


class TestCodeBlocks:
    def test_fenced_code_block(self):
        md = "```\nprint('hello')\n```"
        assert md_to_chatwork(md) == "[code]print('hello')[/code]"

    def test_fenced_code_block_with_language(self):
        md = "```python\nprint('hello')\n```"
        assert md_to_chatwork(md) == "[code]print('hello')[/code]"

    def test_fenced_code_block_multiline(self):
        md = "```python\ndef foo():\n    return 42\n```"
        result = md_to_chatwork(md)
        assert result == "[code]def foo():\n    return 42[/code]"

    def test_inline_code_preserved(self):
        md = "Use `pip install` to install"
        assert md_to_chatwork(md) == "Use `pip install` to install"

    def test_md_inside_code_block_not_converted(self):
        md = "```\n**bold** and *italic*\n```"
        assert md_to_chatwork(md) == "[code]**bold** and *italic*[/code]"


class TestBoldItalicStrike:
    def test_bold(self):
        assert md_to_chatwork("This is **bold** text") == "This is bold text"

    def test_italic(self):
        assert md_to_chatwork("This is *italic* text") == "This is italic text"

    def test_bold_italic(self):
        assert md_to_chatwork("This is ***both*** text") == "This is both text"

    def test_strikethrough(self):
        assert md_to_chatwork("This is ~~deleted~~ text") == "This is deleted text"

    def test_bullet_list_not_converted(self):
        md = "* item1\n* item2"
        result = md_to_chatwork(md)
        assert "* item1" in result
        assert "* item2" in result


class TestHeadings:
    def test_h1(self):
        assert md_to_chatwork("# Title") == "[info][title]Title[/title][/info]"

    def test_h2(self):
        assert md_to_chatwork("## Section") == "[info][title]Section[/title][/info]"

    def test_h3(self):
        assert md_to_chatwork("### Sub") == "[info][title]Sub[/title][/info]"

    def test_heading_with_surrounding_text(self):
        md = "Before\n## Heading\nAfter"
        result = md_to_chatwork(md)
        assert "[info][title]Heading[/title][/info]" in result
        assert "Before" in result
        assert "After" in result

    def test_heading_not_in_middle_of_line(self):
        md = "This is not ## a heading"
        result = md_to_chatwork(md)
        assert "[info]" not in result


class TestLinks:
    def test_link(self):
        md = "Visit [Google](https://google.com) now"
        assert md_to_chatwork(md) == "Visit Google ( https://google.com ) now"

    def test_image(self):
        md = "![logo](https://example.com/img.png)"
        assert md_to_chatwork(md) == "https://example.com/img.png"

    def test_link_and_image_together(self):
        md = "See ![alt](http://img.png) and [link](http://url)"
        result = md_to_chatwork(md)
        assert "http://img.png" in result
        assert "link ( http://url )" in result


class TestHorizontalRule:
    def test_dashes(self):
        assert md_to_chatwork("---") == "[hr]"

    def test_asterisks(self):
        assert md_to_chatwork("***") == "[hr]"

    def test_underscores(self):
        assert md_to_chatwork("___") == "[hr]"

    def test_long_dashes(self):
        assert md_to_chatwork("----------") == "[hr]"

    def test_hr_in_context(self):
        md = "Above\n---\nBelow"
        result = md_to_chatwork(md)
        assert "[hr]" in result
        assert "Above" in result
        assert "Below" in result


class TestBlockquotes:
    def test_single_quote(self):
        md = "> This is quoted"
        assert md_to_chatwork(md) == "[qt]This is quoted[/qt]"

    def test_consecutive_quotes(self):
        md = "> Line 1\n> Line 2\n> Line 3"
        result = md_to_chatwork(md)
        assert result == "[qt]Line 1\nLine 2\nLine 3[/qt]"

    def test_quote_with_surrounding(self):
        md = "Before\n> Quoted\nAfter"
        result = md_to_chatwork(md)
        assert "Before" in result
        assert "[qt]Quoted[/qt]" in result
        assert "After" in result


class TestTables:
    def test_basic_table(self):
        md = "| Name | Age |\n|------|-----|\n| Alice | 30 |\n| Bob | 25 |"
        result = md_to_chatwork(md)
        assert "• Name: Alice | Age: 30" in result
        assert "• Name: Bob | Age: 25" in result

    def test_table_header_only(self):
        md = "| Name | Age |\n|------|-----|"
        result = md_to_chatwork(md)
        assert "• " not in result

    def test_table_with_surrounding_text(self):
        md = "Results:\n| Key | Val |\n|-----|-----|\n| a | 1 |\nEnd"
        result = md_to_chatwork(md)
        assert "Results:" in result
        assert "• Key: a | Val: 1" in result
        assert "End" in result


class TestChatworkTagProtection:
    def test_existing_info_tag(self):
        md = "[info]Important[/info]"
        assert md_to_chatwork(md) == "[info]Important[/info]"

    def test_existing_code_tag(self):
        md = "[code]print('hi')[/code]"
        assert md_to_chatwork(md) == "[code]print('hi')[/code]"

    def test_existing_hr_tag(self):
        md = "Before [hr] After"
        assert md_to_chatwork(md) == "Before [hr] After"

    def test_existing_to_tag(self):
        md = "[To:12345] Hello"
        assert md_to_chatwork(md) == "[To:12345] Hello"

    def test_existing_qt_tag(self):
        md = "[qt]quoted text[/qt]"
        assert md_to_chatwork(md) == "[qt]quoted text[/qt]"

    def test_existing_picon_tag(self):
        md = "[picon:12345] said hello"
        assert md_to_chatwork(md) == "[picon:12345] said hello"

    def test_existing_piconname_tag(self):
        md = "[piconname:12345] said hello"
        assert md_to_chatwork(md) == "[piconname:12345] said hello"

    def test_existing_toall_tag(self):
        md = "[toall] Everyone!"
        assert md_to_chatwork(md) == "[toall] Everyone!"

    def test_mixed_cw_tags_and_md(self):
        md = "[To:123] Hello\n**Important** update\n[hr]\nDone"
        result = md_to_chatwork(md)
        assert "[To:123]" in result
        assert "Important" in result
        assert "**" not in result
        assert "[hr]" in result

    def test_info_with_title_preserved(self):
        md = "[info][title]Notice[/title]Details here[/info]"
        assert md_to_chatwork(md) == "[info][title]Notice[/title]Details here[/info]"


class TestEdgeCases:
    def test_whitespace_only(self):
        assert md_to_chatwork("   ") == "   "

    def test_null_byte_stripped(self):
        result = md_to_chatwork("before\x00PH0\x00after")
        assert "\x00" not in result
        assert "PH0" in result

    def test_blockquote_with_leading_whitespace(self):
        md = "  > indented quote"
        result = md_to_chatwork(md)
        assert result == "[qt]indented quote[/qt]"


class TestCombined:
    def test_realistic_message(self):
        md = (
            "## 進捗報告\n\n"
            "**タスクA** が完了しました。\n\n"
            "変更点:\n"
            "- ファイルXを修正\n"
            "- テスト追加\n\n"
            "```python\ndef test():\n    pass\n```\n\n"
            "詳細は [ドキュメント](https://docs.example.com) を参照。"
        )
        result = md_to_chatwork(md)
        assert "[info][title]進捗報告[/title][/info]" in result
        assert "タスクA" in result
        assert "**" not in result
        assert "[code]def test():\n    pass[/code]" in result
        assert "ドキュメント ( https://docs.example.com )" in result

    def test_message_with_cw_tags_and_md(self):
        md = "[To:999] 山田さん\n\n## 報告\n\n> 前回の結論\n\nOKです。"
        result = md_to_chatwork(md)
        assert "[To:999]" in result
        assert "[info][title]報告[/title][/info]" in result
        assert "[qt]前回の結論[/qt]" in result
        assert "OKです。" in result

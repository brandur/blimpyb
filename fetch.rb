require 'excon'
require 'fileutils'
require 'nokogiri'
require 'reverse_markdown'
require 'sanitize'
require 'time'
require 'toml'

ARTICLES_PATH = "./content/articles"
BASE_URL = "https://web.archive.org/web/20140228064137/http://blimpyb.com/"
IMAGES_PATH = "./content/images/"
MAX_PAGE = 20

def get_page(url, raise_error: true, redirect: false)
  puts "getting: #{url}#{redirect ? " (redirect) " : ""}"
  resp = Excon.get(url)

  if resp.status != 200
    if resp.status == 302
      return get_page(resp.headers["Location"], redirect: true)
    end

    raise("bad status: #{resp.status}") if raise_error
  end

  # puts "body sample: #{resp.body[0..500]}..."

  [resp.status, resp.body]
end

def replace_images(content, slug_with_date)
  images = []

  content.gsub!(%r{^\[!\[\]\((.*) "(.*)"\)\]\((.*)\)$\n\n^(.*)$}) do |match|
    # p match
    thumbnail_url = $1
    alt_text = $2
    full_url = $3
    caption_text = $4

    path = "#{IMAGES_PATH}/#{slug_with_date}"
    puts "creating: #{path}"
    FileUtils.mkdir_p(path)

    thumb_filename = File.basename(thumbnail_url)
    thumbnail_status, thumbnail_body = get_page(thumbnail_url, raise_error: false)
    if thumbnail_status != 404
      puts "writing: #{path}/#{thumb_filename}"
      File.write("#{path}/#{thumb_filename}", thumbnail_body)
    else
      puts "Thumbnail image not found: #{slug_with_date} / #{thumb_filename}"
    end

    full_filename = File.basename(full_url)
    full_status, full_body = get_page(full_url, raise_error: false)
    if full_status != 404
      puts "writing: #{path}/#{full_filename}"
      File.write("#{path}/#{full_filename}", thumbnail_body)
    else
      puts "Full image not found: #{slug_with_date} / #{full_filename}"
    end

    if thumbnail_status != 404 && full_status != 404
      <<~EOS.strip
        <figure>
            <a href="../images/#{slug_with_date}/#{full_filename}">
                <img src="../images/#{slug_with_date}/#{thumb_filename}" alt="#{alt_text}">
            </a>
            <figcaption>#{caption_text}</figcaption>
        </figure>
      EOS
    elsif thumbnail_status != 404
      <<~EOS.strip
        <figure>
            <img src="../images/#{slug_with_date}/#{thumb_filename}" alt="#{alt_text}">
            <figcaption>#{caption_text}</figcaption>
        </figure>
      EOS
    else
      "_(missing image)_ (**caption:** #{caption_text})"
    end
  end

  content
end

def sanitize_content(content)
  content.gsub!(%r{<p>\*\*\*/</p>}, "\n---\n")

  content = ReverseMarkdown.convert(content)

  content.gsub!(/^Popularity:.*$/, '')

  # content.gsub!("\r", "\n")

  # kill double spacing in sentences
  content.gsub!(/&nbsp; /, ' ')

  content = Sanitize.fragment(content, Sanitize::Config::RESTRICTED)

  # collapse multiple newlines
  content.gsub!(%r{(\s*\n\s*){2,}}, "\n\n")

  content.strip!

  content
end

# inclusive
for i in 1..MAX_PAGE do
  url = if i == 1
    BASE_URL
  else
    BASE_URL + "page/#{i}/"
  end

  _status, body = get_page(url)

  html = Nokogiri::HTML(body)
  html.css('.boxpost h2 a').each_with_index do |element, j|
    entry_url = element.attributes["href"]
    path_segments = entry_url.value.split("/")
    slug = path_segments[path_segments.count - 2]
    title = element.text

    puts "\n\n---\n#{title} (#{slug})\n---\n\n"

    _status, entry_body = get_page(entry_url)

    entry_html = Nokogiri::HTML(entry_body)

    published_at = nil
    entry_html.css('#content .post .clock').each do |clock_element|
      #  e.g. " On February - 2 - 2012"
      published_at = Time.strptime(clock_element.text, " On %B - %d - %Y")
    end

    raise "no published_at for #{slug}!" if published_at.nil?

    slug_with_date = "#{published_at.strftime("%Y-%m-%d")}-#{slug}"

    entry_content = entry_html.css('.entry').to_html
    entry_content = sanitize_content(entry_content)
    entry_content = replace_images(entry_content, slug_with_date)

=begin
    entry_html.css('.entry').each do |entry_element|
      puts "found entry"
      i = 0
    end
=end

    toml_data = TOML::Generator.new({
      "title" => title,
      "published_at" => published_at.to_datetime.rfc3339,
    }).body

    filename = "#{ARTICLES_PATH}/#{slug_with_date}.md"
    puts "writing: #{filename}"

    File.write(filename, <<~EOS)
      +++
      #{toml_data.strip}
      +++

      # #{title}

      #{entry_content}
    EOS

    break if j > 1
  end

  break
  sleep(1)
end

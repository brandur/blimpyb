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

def download_file(source_url, target_file)
  if File.exist?(target_file)
    puts "File exists: #{target_file}; skipping"
    return true
  end

  status, body, _final_url = get_url(source_url, raise_error: false)
  if status == 404
    puts "URL not found: #{source_url} / #{target_file}"
    return false
  end

  dir = File.dirname(target_file)
  if !File.directory?(dir)
    puts "creating: #{dir}"
    FileUtils.mkdir_p(dir)
  end

  puts "writing: #{target_file}"
  File.write("#{target_file}", body)

  true
end

def get_url(url, raise_error: true, redirect: false)
  puts "getting: #{url}#{redirect ? " (redirect) " : ""}"
  resp = Excon.get(url)

  if resp.status != 200
    if resp.status == 302
      return get_url(resp.headers["Location"], redirect: true)
    end

    raise("bad status: #{resp.status}") if raise_error
  end

  # puts "body sample: #{resp.body[0..500]}..."

  [resp.status, resp.body, url]
end

def replace_images(content, slug_with_date)
  images = []

  content.gsub!(%r{^\[!\[\]\((.*) "(.*)"\)\]\((.*)\)$\n\n^(.*)$}) do |match|
    thumbnail_url = $1
    alt_text = $2
    full_url = $3
    caption_text = $4

    path = "#{IMAGES_PATH}/#{slug_with_date}"

    thumbnail_filename = File.basename(thumbnail_url)
    thumbnail_exists = download_file(thumbnail_url, "#{path}/#{thumbnail_filename}")

    full_filename = File.basename(full_url)
    full_exists = download_file(full_url, "#{path}/#{full_filename}")

    if thumbnail_exists && full_exists
      <<~EOS.strip
        <p text-align="center">
            <figure>
                <a href="../images/#{slug_with_date}/#{full_filename}">
                    <img src="../images/#{slug_with_date}/#{thumbnail_filename}" alt="#{alt_text}">
                </a>
                <figcaption><strong>#{caption_text}</strong></figcaption>
            </figure>
        </p>
      EOS
    elsif thumbnail_exists
      <<~EOS.strip
        <p text-align="center">
            <figure>
                <img src="../images/#{slug_with_date}/#{thumbnail_filename}" alt="#{alt_text}">
                <figcaption><strong>#{caption_text}</strong></figcaption>
            </figure>
        </p>
      EOS
    else
      "_(missing image)_ (**caption:** #{caption_text}; **alt:** #{alt_text})"
    end
  end

  content
end

def sanitize_content(content)
  content.gsub!(%r{<p>\*\*\*/</p>}, "\n---\n")

  content = ReverseMarkdown.convert(content)

  content.gsub!(/^Popularity:.*$/, '')

  content.gsub!(%r{_ \*\*([^\*]+)\*\* _}, '_**\1**_')

  # kill double spacing in sentences
  content.gsub!(/&nbsp; /, ' ')

  content = Sanitize.fragment(content, Sanitize::Config::RESTRICTED)

  # fix blockquotes mauled by Sanitiz
  content.gsub!(%r{^&gt; }, '> ')

  # fix lists inside of blockquotes
  content.gsub!(%r{> -}, '> * ')

  # get rid of blockquotes with empty space after them
  content.gsub!(%r{>\s+$}, '>')

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

  _status, body, _final_url = get_url(url)

  html = Nokogiri::HTML(body)
  html.css('.boxpost h2 a').each_with_index do |element, j|
    entry_url = element.attributes["href"]
    path_segments = entry_url.value.split("/")
    slug = path_segments[path_segments.count - 2]
    title = element.text

    puts "\n\n---\n#{title} (#{slug})\n---\n\n"

    _status, entry_body, final_entry_url = get_url(entry_url)

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
      "wayback_machine_url" => final_entry_url,
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
